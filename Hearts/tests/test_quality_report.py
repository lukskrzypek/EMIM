"""Bot quality report: model label in the log, log parsing, ignore filter, ``0`` players mode."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import main
from controllers.base import PlayerController
from controllers.ai_bot import AIBot
from controllers.human_cli import HumanCLIController
from controllers.smart_bot import SmartHeartsBot
from engine.observation import PlayerObservation
from engine.state import GameState
from evaluation.report import evaluate_log, format_report
from evaluation.trajectories import UNKNOWN_MODEL, load_moves
from utils.icl_logger import ICLLogger


class _Labelled(SmartHeartsBot):
    """Smart bot that reports another controller name."""

    def __init__(self, name: str, seed: int) -> None:
        super().__init__(num_samples=0, seed=seed)
        self.model_name = name


class _FirstLegal(PlayerController):
    model_name = "dummy-llm"

    def select_move(self, observation: PlayerObservation) -> str:
        return observation.legal_moves[0]


def _play_deal(
    state: GameState, controllers: dict[str, PlayerController], logger: ICLLogger
) -> None:
    """Play and log the current deal only (the log gets one deal's worth of records)."""
    state.auto_advance = False
    while not (state.deal_finished or state.is_over):
        pid = state.current_player
        assert pid is not None
        observation = state.get_player_observation(pid)
        controller = controllers[pid]
        chosen = controller.select_move(observation)
        logger.log(observation, chosen, controller.last_reasoning, controller.model_name)
        state.play_card(pid, chosen)


def _play(path: Path, players: int, names: list[str], deals: int = 1, seed: int = 0) -> None:
    """Log ``deals`` deals; deal ``k`` uses the k-th contract of the King order."""
    logger = ICLLogger(path)
    controllers: dict[str, PlayerController] = {
        f"P{i}": _Labelled(name, seed + i) for i, name in enumerate(names)
    }
    for deal in range(deals):
        state = GameState.new(players, seed=seed + deal, start_deal=deal % 7 + 1)
        _play_deal(state, controllers, logger)


def _records(path: Path) -> list[dict[str, object]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


# ------------------------------------------------------------- model label

def test_controllers_name_themselves() -> None:
    assert HumanCLIController().model_name == "human"
    assert SmartHeartsBot(num_samples=0).model_name == "smart_bot"
    assert AIBot("P0").model_name == "openai/gpt-oss-120b"
    assert AIBot("P0", model="other/model").model_name == "other/model"
    assert _FirstLegal.model_name == "dummy-llm"


def test_logger_writes_model_field(tmp_path: Path) -> None:
    path = tmp_path / "t.jsonl"
    state = GameState.new(4, seed=1)
    obs = state.get_player_observation("P0")
    ICLLogger(path).log(obs, obs.legal_moves[0], "why", "some-model")
    ICLLogger(path).log(obs, obs.legal_moves[0])
    first, second = _records(path)
    assert first["model"] == "some-model"
    assert second["model"] == "unknown"


def test_play_match_logs_the_model_of_the_seat(tmp_path: Path) -> None:
    path = tmp_path / "t.jsonl"
    state = GameState.new(3, seed=2)
    controllers: dict[str, PlayerController] = {
        "P0": _FirstLegal(),
        "P1": SmartHeartsBot(num_samples=0, seed=0),
        "P2": SmartHeartsBot(num_samples=0, seed=1),
    }
    main.play_match(state, controllers, ICLLogger(path), show_play=False)
    seen = {(r["player_id"], r["model"]) for r in _records(path)}
    assert seen == {("P0", "dummy-llm"), ("P1", "smart_bot"), ("P2", "smart_bot")}


# ---------------------------------------------------------------- log parsing

@pytest.mark.parametrize("players", [3, 4])
def test_every_logged_move_is_reconstructed_and_rated(tmp_path: Path, players: int) -> None:
    path = tmp_path / "t.jsonl"
    _play(path, players, [f"m{i}" for i in range(players)], deals=3)
    loaded = load_moves(path)
    cards = (52 - {3: 1, 4: 0}[players]) * 3
    assert loaded.records == cards
    assert len(loaded.moves) == cards
    assert not loaded.skipped
    report = evaluate_log(path)
    assert not report.skipped
    assert sum(m.moves for m in report.models.values()) == cards
    assert all(m.illegal == 0 for m in report.models.values())
    assert set(report.models) == {f"m{i}" for i in range(players)}


def test_history_is_rebuilt_beyond_the_eight_tricks_shown_in_the_prompt(tmp_path: Path) -> None:
    path = tmp_path / "t.jsonl"
    _play(path, 4, ["a", "b", "c", "d"])
    last = load_moves(path).moves[-1]
    assert len(last.state.history) == 12
    assert all(len(trick) == 4 for trick in last.state.history)
    assert len(last.state.hand) == 1


def test_records_without_model_field_are_unknown(tmp_path: Path) -> None:
    path = tmp_path / "t.jsonl"
    _play(path, 3, ["a", "b", "c"])
    stripped = []
    for record in _records(path):
        record.pop("model")
        stripped.append(json.dumps(record))
    path.write_text("\n".join(stripped) + "\n\n", encoding="utf-8")
    loaded = load_moves(path)
    assert {m.model for m in loaded.moves} == {UNKNOWN_MODEL}
    assert loaded.records == len(stripped)  # the blank line is not a record


def test_damaged_deal_is_skipped_and_next_deal_still_counts(tmp_path: Path) -> None:
    path = tmp_path / "t.jsonl"
    _play(path, 3, ["a", "b", "c"], deals=2)
    lines = path.read_text(encoding="utf-8").splitlines()
    per_deal = len(lines) // 2
    broken = lines[:10] + ["{not json"] + lines[11:per_deal] + lines[per_deal:]
    path.write_text("\n".join(broken) + "\n", encoding="utf-8")
    loaded = load_moves(path)
    assert loaded.skipped
    # first deal: only the 10 records before the damage survive
    assert len(loaded.moves) == 10 + per_deal
    assert loaded.skipped.total() == len(lines) - 10 - per_deal


def test_interrupted_deal_does_not_break_the_next_one(tmp_path: Path) -> None:
    path = tmp_path / "t.jsonl"
    _play(path, 3, ["a", "b", "c"], deals=2, seed=4)
    lines = path.read_text(encoding="utf-8").splitlines()
    per_deal = len(lines) // 2
    path.write_text("\n".join(lines[:7] + lines[per_deal:]) + "\n", encoding="utf-8")
    loaded = load_moves(path)
    assert not loaded.skipped
    assert len(loaded.moves) == 7 + per_deal


# ------------------------------------------------------------ ignore filter

def test_ignored_players_are_left_out(tmp_path: Path) -> None:
    path = tmp_path / "t.jsonl"
    _play(path, 4, ["human", "smart_bot", "llm-a", "llm-b"], deals=2)
    report = evaluate_log(path, ("human", "smart_bot"))
    assert set(report.models) == {"llm-a", "llm-b"}
    assert set(report.ignored) == {"human", "smart_bot"}
    assert sum(report.ignored.values()) + sum(m.moves for m in report.models.values()) == 104
    text = format_report(report)
    assert "Ignorowani: human, smart_bot" in text
    assert "llm-a" in text and "\nhuman" not in text


def test_ignore_filter_is_case_insensitive_and_optional(tmp_path: Path) -> None:
    path = tmp_path / "t.jsonl"
    _play(path, 3, ["Human", "llm", "llm2"])
    assert set(evaluate_log(path, ("human",)).models) == {"llm", "llm2"}
    assert set(evaluate_log(path, ()).models) == {"Human", "llm", "llm2"}


def test_default_ignore_list_covers_human_and_smart_bot() -> None:
    assert set(main.IGNORED_PLAYERS) == {"human", "smart_bot"}


# ------------------------------------------------------------------ metrics

def test_forced_moves_do_not_inflate_quality(tmp_path: Path) -> None:
    path = tmp_path / "t.jsonl"
    _play(path, 4, ["a", "b", "c", "d"], deals=2)
    report = evaluate_log(path)
    for stats in report.models.values():
        assert stats.forced > 0
        assert stats.decisions == stats.moves - stats.forced
        assert stats.correctness is not None and 0 <= stats.correctness <= 100
        assert sum(stats.verdicts.values()) == stats.decisions
        assert sum(len(v) for v in stats.scenarios.values()) == stats.decisions


def test_better_play_scores_higher_than_always_first_legal_card(tmp_path: Path) -> None:
    path = tmp_path / "t.jsonl"
    logger = ICLLogger(path)
    for seed in range(12):
        state = GameState.new(4, seed=seed, start_deal=(seed % 7) + 1)
        controllers: dict[str, PlayerController] = {
            "P0": SmartHeartsBot(num_samples=0, seed=seed),
            "P1": _FirstLegal(),
            "P2": SmartHeartsBot(num_samples=0, seed=seed + 1),
            "P3": _FirstLegal(),
        }
        _play_deal(state, controllers, logger)
    report = evaluate_log(path)
    smart = report.models["smart_bot"].correctness
    naive = report.models["dummy-llm"].correctness
    assert smart is not None and naive is not None
    assert smart > naive


def test_empty_selection_reports_no_moves(tmp_path: Path) -> None:
    path = tmp_path / "t.jsonl"
    _play(path, 3, ["human", "smart_bot", "smart_bot"])
    text = format_report(evaluate_log(path, ("human", "smart_bot")))
    assert "Brak ruchów do oceny" in text


# ------------------------------------------------------------ 0-player mode

def test_ask_players_accepts_zero(monkeypatch: pytest.MonkeyPatch) -> None:
    answers = iter(["7", "2", "0"])
    monkeypatch.setattr("builtins.input", lambda _: next(answers))
    assert main._ask_players() == 0


def test_zero_players_runs_the_report_instead_of_a_game(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []
    monkeypatch.setattr("builtins.input", lambda _: "0")
    monkeypatch.setattr(main, "run_quality_report", lambda: calls.append("report") or True)
    monkeypatch.setattr(main, "setup_match", lambda *_: pytest.fail("a game was started"))
    main.main()
    assert calls == ["report"]


def test_nonzero_players_still_start_a_game(monkeypatch: pytest.MonkeyPatch) -> None:
    started: list[int] = []

    def fake_setup(players: int | None = None) -> tuple[int, dict[str, PlayerController], int, bool]:
        assert players is not None
        started.append(players)
        return players, {f"P{i}": SmartHeartsBot(num_samples=0, seed=i) for i in range(players)}, 1, False

    monkeypatch.setattr("builtins.input", lambda _: "3")
    monkeypatch.setattr(main, "setup_match", fake_setup)
    monkeypatch.setattr(main, "run_quality_report", lambda: pytest.fail("report instead of game"))
    monkeypatch.setattr(main, "LOG_PATH", Path("unused.jsonl"))
    monkeypatch.setattr(main, "ICLLogger", lambda _path: _NullLogger())
    main.main()
    assert started == [3]


class _NullLogger(ICLLogger):
    def __init__(self) -> None:
        pass

    def log(self, *args: object, **kwargs: object) -> None:
        return None


def test_run_quality_report_prints_table(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    path = tmp_path / "t.jsonl"
    _play(path, 4, ["human", "smart_bot", "llm-a", "llm-b"])
    assert main.run_quality_report(path, ("human", "smart_bot")) is True
    out = capsys.readouterr().out
    assert "Ocena jakości ruchów botów" in out
    assert "llm-a" in out and "llm-b" in out


def test_run_quality_report_without_log(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main.run_quality_report(tmp_path / "missing.jsonl") is False
    assert "Brak logu" in capsys.readouterr().out
