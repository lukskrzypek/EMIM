"""Startup options: a sitting-out player chooses how many deals the bots play."""

from __future__ import annotations

from pathlib import Path

import pytest

from controllers.smart_bot import SmartHeartsBot
from engine.game import TOTAL_POINTS
from utils.icl_logger import ICLLogger
import main


def _bots() -> dict[str, SmartHeartsBot]:
    return {f"P{i}": SmartHeartsBot(num_samples=0, seed=i) for i in range(main.NUM_PLAYERS)}


def test_ask_deal_count_rejects_then_accepts(monkeypatch: pytest.MonkeyPatch) -> None:
    answers = iter(["0", "x", "3"])
    monkeypatch.setattr("builtins.input", lambda _: next(answers))
    assert main._ask_deal_count() == 3


def test_ask_yes_no(monkeypatch: pytest.MonkeyPatch) -> None:
    answers = iter(["moze", "n"])
    monkeypatch.setattr("builtins.input", lambda _: next(answers))
    assert main._ask_yes_no("?") is False


def test_session_simulates_requested_number_of_deals(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    deals = 3
    totals = main.play_session(
        main.NUM_PLAYERS,
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
        main.NUM_PLAYERS,
        _bots(),
        ICLLogger(tmp_path / "trajectories.jsonl"),
        deals=1,
        show_play=True,
    )
    output = capsys.readouterr().out
    assert "Ręce:" in output
    assert "T1:" in output
    assert "Partia 1:" not in output


def test_session_rejects_non_positive_deal_count(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        main.play_session(
            main.NUM_PLAYERS,
            _bots(),
            ICLLogger(tmp_path / "trajectories.jsonl"),
            deals=0,
            show_play=False,
        )
