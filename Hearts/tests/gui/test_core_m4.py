"""Report service, persisted lobby state and the Params schema (Qt-free)."""

from __future__ import annotations

import json
from dataclasses import fields
from pathlib import Path

import pytest
from collector import Collector
from controllers.smart_bot import SmartHeartsBot
from engine.game import HeartsGameEngine
from evaluation.params import Params
from evaluation.report import build_report
from evaluation.trajectories import load_moves
from gui.config import IGNORED_PLAYERS
from gui.core.events import MovePlayed
from gui.core.game_runner import GameRunner
from gui.core.live_evaluator import LiveEvaluator
from gui.core.lobby_state import LobbyState, default_seats
from gui.core.pace import PaceControl
from gui.core.params_schema import is_default, param_fields, with_values
from gui.core.report_service import load_report, parse_ignored
from gui.core.seat_config import SeatConfig, SeatKind, SessionConfig
from test_core_live_quality import _play


# ------------------------------------------------------------------- report


def test_parse_ignored() -> None:
    assert parse_ignored("human, smart_bot ,, human") == ("human", "smart_bot")
    assert parse_ignored("") == ()


def test_report_of_a_real_log_equals_the_library_report(tmp_path: Path) -> None:
    log = tmp_path / "trajectories.jsonl"
    _play(4, seed=21, log=log, deals=2)

    result = load_report(log, ())
    assert result.error is None and result.report is not None
    expected = build_report(load_moves(log))
    assert set(result.report.models) == set(expected.models) == {"smart_bot", "last_legal"}
    for name, model in expected.models.items():
        assert result.report.models[name].correctness == pytest.approx(model.correctness)
    assert "Ocena jakości ruchów botów" in result.text


def test_report_can_leave_models_out(tmp_path: Path) -> None:
    log = tmp_path / "trajectories.jsonl"
    _play(3, seed=2, log=log)
    result = load_report(log, ("smart_bot",))
    assert result.report is not None
    assert set(result.report.models) == {"last_legal"}
    assert result.report.ignored["smart_bot"] > 0
    assert result.ignored_models == ("smart_bot",)


def test_report_problems_come_back_as_text(tmp_path: Path) -> None:
    missing = load_report(tmp_path / "nope.jsonl")
    assert missing.report is None and "Brak pliku" in (missing.error or "")

    broken = tmp_path / "broken.jsonl"
    broken.write_bytes(b"\xff\xfe\x00 not utf-8 \xff\n")
    result = load_report(broken)
    assert result.report is None and result.error

    garbage = tmp_path / "garbage.jsonl"
    garbage.write_text("{not json}\n\n[]\n", encoding="utf-8")
    parsed = load_report(garbage)  # unreadable records are counted, not fatal
    assert parsed.report is not None and parsed.report.models == {}
    assert sum(parsed.report.skipped.values()) == 2


def test_default_ignored_players_match_main() -> None:
    import main

    assert tuple(IGNORED_PLAYERS) == tuple(main.IGNORED_PLAYERS)


# -------------------------------------------------------------- lobby state


def test_lobby_state_round_trip() -> None:
    seats = list(default_seats())
    seats[1] = SeatConfig(SeatKind.GROQ, groq_model="openai/gpt-oss-20b",
                          groq_guidelines="Prefer ducking early.", groq_name="bold")
    seats[2] = SeatConfig(SeatKind.SMART, smart_samples=0)
    state = LobbyState(players=3, deals=25, seats=tuple(seats))
    assert LobbyState.from_json(state.to_json()) == state


@pytest.mark.parametrize("text", [None, "", "{{{", "[]", "null", "42", '"x"'])
def test_lobby_state_survives_garbage(text: str | None) -> None:
    assert LobbyState.from_json(text) == LobbyState()


def test_lobby_state_repairs_bad_fields() -> None:
    raw = {
        "players": 9,
        "deals": 10**9,
        "fixed_seed": 1,  # options of older versions are ignored
        "seed": -4,
        "seats": [
            {"kind": "robot"},
            {
                "kind": "groq", "groq_model": "  ", "groq_examples": 999, "smart_samples": "x",  # old key: ignored
                "groq_guidelines": "line one\n" + "x" * 300, "groq_name": "a b/c" + "z" * 20,
            },
            "oops",
            {"kind": "smart", "smart_samples": 12},
        ],
    }
    state = LobbyState.from_json(json.dumps(raw))
    assert state.players == 4  # not one of 2-5
    assert state.deals == 1000  # clamped
    assert state.seats[1].groq_name == "a_b_c" + "z" * 5  # file-safe and 10 characters at most
    guidelines = state.seats[1].groq_guidelines
    assert len(guidelines) == 100 and "\n" not in guidelines and guidelines.startswith("line one x")
    assert state.seats[0].kind is SeatKind.HUMAN  # unknown kind -> default seat
    assert state.seats[1].kind is SeatKind.GROQ and not hasattr(state.seats[1], "groq_examples")
    assert state.seats[1].groq_model  # blank model -> a usable one
    assert state.seats[2] == default_seats()[2]
    assert state.seats[3].smart_samples == 12
    assert len(state.seats) == 5


# ------------------------------------------------------------------- params


def test_schema_covers_every_param_with_sections_and_hints() -> None:
    schema = param_fields()
    assert [f.name for f in schema] == [f.name for f in fields(Params)]
    by_name = {f.name: f for f in schema}
    assert by_name["heavy_min_cards"].kind is int
    assert by_name["overtake_rate"].kind is float
    assert by_name["overtake_rate"].default == 0.7
    assert by_name["lead_last_card_relief"].hint  # a hint spread over two comment lines is joined
    assert "zrzutu kar" in by_name["lead_last_card_relief"].hint
    assert len({f.section for f in schema}) >= 4
    assert all(f.hint for f in schema)


def test_with_values_changes_only_known_fields_and_types() -> None:
    changed = with_values(Params(), {"overtake_rate": 0.2, "heavy_min_cards": 5.0, "nonsense": 1})
    assert changed.overtake_rate == 0.2
    assert changed.heavy_min_cards == 5 and isinstance(changed.heavy_min_cards, int)
    assert not hasattr(changed, "nonsense")
    assert Params().overtake_rate == 0.7  # the original is untouched
    assert is_default(None) and is_default(Params()) and not is_default(changed)


def _aggressiveness(evaluator: LiveEvaluator) -> float:
    sink = Collector()
    config = SessionConfig((SeatConfig(SeatKind.SMART, smart_samples=0),) * 4, log_path=None)
    runner = GameRunner(
        config,
        sink,
        pace=PaceControl(0),
        controllers={f"P{i}": SmartHeartsBot(num_samples=0, seed=i) for i in range(4)},
        analyzer=evaluator,
        engine_factory=lambda n, k: HeartsGameEngine(n, seed=9),
    )
    runner.start()
    sink.wait_finished(timeout=30)
    values = [
        e.analysis.chosen_eval.aggressiveness
        for e in sink.of(MovePlayed)
        if e.analysis.chosen_eval.aggressiveness is not None
    ]
    return sum(values) / len(values)


def test_custom_params_reach_the_live_evaluation() -> None:
    calm = Params(take_aggr_base=0.0, take_aggr_progress=0.0, void_aggr=0.0, risk_aggr=0.0)
    assert _aggressiveness(LiveEvaluator(calm)) < _aggressiveness(LiveEvaluator())
