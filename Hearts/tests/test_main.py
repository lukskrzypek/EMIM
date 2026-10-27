"""Startup options: player count, a controller per seat, match count when no human sits."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from controllers.base import PlayerController
from controllers.ai_bot import AIBot
from controllers.human_cli import HumanCLIController
from controllers.smart_bot import SmartHeartsBot
from engine.contracts import CONTRACT_ORDER, contract_total_penalty
from engine.observation import PlayerObservation
from engine.state import GameState
from utils.icl_logger import ICLLogger
import main


def _bots(num_players: int = 4) -> dict[str, SmartHeartsBot]:
    return {f"P{i}": SmartHeartsBot(num_samples=0, seed=i) for i in range(num_players)}


def _match_total(num_players: int) -> int:
    return sum(contract_total_penalty(c, num_players) for c in CONTRACT_ORDER)


def _answers(monkeypatch: pytest.MonkeyPatch, *values: str) -> None:
    pending = iter(values)
    monkeypatch.setattr("builtins.input", lambda _: next(pending))


def test_ask_match_count_rejects_then_accepts(monkeypatch: pytest.MonkeyPatch) -> None:
    _answers(monkeypatch, "0", "x", "3")
    assert main._ask_match_count() == 3


def test_ask_players_rejects_then_accepts(monkeypatch: pytest.MonkeyPatch) -> None:
    _answers(monkeypatch, "1", "2", "5", "6", "3")
    assert main._ask_players() == 3


def test_ask_players_accepts_quality_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    _answers(monkeypatch, "0")
    assert main._ask_players() == main.QUALITY_MODE


def test_setup_assigns_a_controller_to_every_seat(monkeypatch: pytest.MonkeyPatch) -> None:
    # 3 players: human, smart, groq. A human sits, so the match count is not asked.
    _answers(monkeypatch, "3", "1", "2", "3")
    num_players, controllers, matches, show_play = main.setup_match()
    assert num_players == 3
    assert matches == 1 and show_play is False
    assert list(controllers) == ["P0", "P1", "P2"]
    assert isinstance(controllers["P0"], HumanCLIController)
    assert isinstance(controllers["P1"], SmartHeartsBot)
    assert isinstance(controllers["P2"], AIBot)
    assert controllers["P2"].player_id == "P2"


def test_setup_asks_match_count_only_when_nobody_plays(monkeypatch: pytest.MonkeyPatch) -> None:
    _answers(monkeypatch, "3", "2", "3", "2", "4")
    num_players, controllers, matches, show_play = main.setup_match()
    assert num_players == 3
    assert matches == 4 and show_play is False
    assert isinstance(controllers["P0"], SmartHeartsBot)
    assert isinstance(controllers["P2"], SmartHeartsBot)
    assert isinstance(controllers["P1"], AIBot)


def test_setup_shows_a_single_bot_match(monkeypatch: pytest.MonkeyPatch) -> None:
    _answers(monkeypatch, "3", "2", "2", "2", "1")
    _, _, matches, show_play = main.setup_match()
    assert matches == 1 and show_play is True


@pytest.mark.parametrize("players", [3, 4])
def test_session_simulates_requested_number_of_matches(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], players: int
) -> None:
    matches = 2
    totals = main.play_session(
        players,
        _bots(players),
        ICLLogger(tmp_path / "trajectories.jsonl"),
        matches=matches,
        show_play=False,
        seed=1,
    )
    assert sum(totals.values()) == _match_total(players) * matches
    output = capsys.readouterr().out
    for number in range(1, matches + 1):
        assert f"Partia {number}:" in output
    assert "Średnia:" in output
    assert "Wygrane:" in output


def test_single_simulated_match_is_shown_card_by_card(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    main.play_session(
        3,
        _bots(3),
        ICLLogger(tmp_path / "trajectories.jsonl"),
        matches=1,
        show_play=True,
        seed=2,
    )
    output = capsys.readouterr().out
    assert "Ręce:" in output
    assert "Rozdanie 1/7" in output and "Rozdanie 7/7" in output
    assert "T1:" in output
    assert "Partia 1:" not in output


class _Noted(PlayerController):
    def select_move(self, observation: PlayerObservation) -> str:
        self.last_reasoning = "ducked"
        return observation.legal_moves[0]


def test_play_match_writes_controller_reasoning(tmp_path: Path) -> None:
    state = GameState.new(4, seed=1)
    controllers = {pid: _Noted() for pid in state.player_ids}
    path = tmp_path / "trajectories.jsonl"
    totals = main.play_match(state, controllers, ICLLogger(path), show_play=False)
    record = json.loads(path.read_text(encoding="utf-8").splitlines()[0])
    assert record["reasoning"] == "ducked"
    assert sum(totals.values()) == _match_total(4)
    assert state.is_over


def test_session_rejects_non_positive_match_count(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        main.play_session(
            4,
            _bots(),
            ICLLogger(tmp_path / "trajectories.jsonl"),
            matches=0,
            show_play=False,
        )
