"""Startup options: player count, a controller per seat, deal count when no human sits."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from controllers.base import PlayerController
from controllers.ai_bot import AIBot
from controllers.human_cli import HumanCLIController
from controllers.smart_bot import SmartHeartsBot
from engine.game import TOTAL_POINTS, HeartsGameEngine, PlayerObservation
from utils.icl_logger import ICLLogger
import main


def _bots(num_players: int = 2) -> dict[str, SmartHeartsBot]:
    return {f"P{i}": SmartHeartsBot(num_samples=0, seed=i) for i in range(num_players)}


def _answers(monkeypatch: pytest.MonkeyPatch, *values: str) -> None:
    pending = iter(values)
    monkeypatch.setattr("builtins.input", lambda _: next(pending))


def test_ask_deal_count_rejects_then_accepts(monkeypatch: pytest.MonkeyPatch) -> None:
    answers = iter(["0", "x", "3"])
    monkeypatch.setattr("builtins.input", lambda _: next(answers))
    assert main._ask_deal_count() == 3


def test_ask_players_rejects_then_accepts(monkeypatch: pytest.MonkeyPatch) -> None:
    _answers(monkeypatch, "1", "6", "3")
    assert main._ask_players() == 3


def test_setup_assigns_a_controller_to_every_seat(monkeypatch: pytest.MonkeyPatch) -> None:
    # 3 players: human, smart, groq. A human sits, so the deal count is not asked.
    _answers(monkeypatch, "3", "1", "2", "3")
    num_players, controllers, deals, show_play = main.setup_match()
    assert num_players == 3
    assert deals == 1 and show_play is False
    assert list(controllers) == ["P0", "P1", "P2"]
    assert isinstance(controllers["P0"], HumanCLIController)
    assert isinstance(controllers["P1"], SmartHeartsBot)
    assert isinstance(controllers["P2"], AIBot)
    assert controllers["P2"].player_id == "P2"


def test_setup_asks_deal_count_only_when_nobody_plays(monkeypatch: pytest.MonkeyPatch) -> None:
    _answers(monkeypatch, "2", "2", "3", "4")
    num_players, controllers, deals, show_play = main.setup_match()
    assert num_players == 2
    assert deals == 4 and show_play is False
    assert isinstance(controllers["P0"], SmartHeartsBot)
    assert isinstance(controllers["P1"], AIBot)


def test_setup_shows_a_single_bot_deal(monkeypatch: pytest.MonkeyPatch) -> None:
    _answers(monkeypatch, "2", "2", "2", "1")
    _, _, deals, show_play = main.setup_match()
    assert deals == 1 and show_play is True


def test_session_simulates_requested_number_of_deals(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    deals = 3
    totals = main.play_session(
        2,
        _bots(),
        ICLLogger(tmp_path / "trajectories.jsonl"),
        deals=deals,
        show_play=False,
    )
    assert sum(totals.values()) == TOTAL_POINTS * deals
    output = capsys.readouterr().out
    for deal in range(1, deals + 1):
        assert f"Partia {deal}:" in output
    assert "Średnia:" in output
    assert "Wygrane:" in output


def test_single_simulated_deal_is_shown_card_by_card(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    main.play_session(
        2,
        _bots(),
        ICLLogger(tmp_path / "trajectories.jsonl"),
        deals=1,
        show_play=True,
    )
    output = capsys.readouterr().out
    assert "Ręce:" in output
    assert "T1:" in output
    assert "Partia 1:" not in output


class _Noted(PlayerController):
    def select_move(self, observation: PlayerObservation) -> str:
        self.last_reasoning = "ducked"
        return observation.legal_moves[0]


def test_play_deal_writes_controller_reasoning(tmp_path: Path) -> None:
    engine = HeartsGameEngine(2, seed=1)
    controllers = {pid: _Noted() for pid in engine.player_ids}
    path = tmp_path / "trajectories.jsonl"
    main.play_deal(engine, controllers, ICLLogger(path), show_play=False)
    record = json.loads(path.read_text(encoding="utf-8").splitlines()[0])
    assert record["reasoning"] == "ducked"


def test_session_rejects_non_positive_deal_count(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        main.play_session(
            2,
            _bots(),
            ICLLogger(tmp_path / "trajectories.jsonl"),
            deals=0,
            show_play=False,
        )
