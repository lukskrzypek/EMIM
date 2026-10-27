"""GameRunner: parity with ``main.play_match``, pacing, human seats, errors, analyzer hook."""

from __future__ import annotations

import threading
import time
from pathlib import Path

import pytest

import main
from collector import Collector
from controllers.base import PlayerController
from controllers.smart_bot import SmartHeartsBot
from engine.contracts import GameContract, contract_total_penalty
from engine.observation import PlayerObservation
from engine.state import GameState
from gui.core.events import (
    ControllerError,
    DealFinished,
    DealStarted,
    GameEvent,
    MovePlayed,
    Notice,
    PauseChanged,
    SessionFinished,
    TrickCompleted,
    TurnStarted,
)
from gui.core.game_runner import AnalysisInput, ErrorResolution, GameRunner
from gui.core.human_controller import HumanGuiController
from gui.core.pace import PaceControl
from gui.core.seat_config import SeatConfig, SeatKind, SessionConfig
from utils.icl_logger import ICLLogger


def _config(n: int = 3, kind: SeatKind = SeatKind.SMART, **kw) -> SessionConfig:  # type: ignore[no-untyped-def]
    seats = tuple(SeatConfig(kind, smart_samples=0) for _ in range(n))
    return SessionConfig(seats, log_path=None, **kw)


def _bots(n: int, samples: int = 3) -> dict[str, PlayerController]:
    return {f"P{i}": SmartHeartsBot(num_samples=samples, seed=i) for i in range(n)}


def _state(n: int, seed: int, deals: int = 1) -> GameState:
    """A match that starts ``deals`` deals before the end (a full match is 21/28 deals)."""
    return GameState.new(n, seed=seed, start_deal=n * 7 - deals + 1)


def _factory(seed: int, deals: int = 1):  # type: ignore[no-untyped-def]
    return lambda n: _state(n, seed, deals)


class FirstLegal(PlayerController):
    model_name = "first_legal"

    def select_move(self, observation: PlayerObservation) -> str:
        self.last_reasoning = "first"
        return observation.legal_moves[0]


# ------------------------------------------------------------------- parity


@pytest.mark.parametrize("players", [3, 4])
def test_runner_reproduces_main_play_match(tmp_path: Path, players: int) -> None:
    expected_log = tmp_path / "main.jsonl"
    expected = main.play_match(
        _state(players, 7, deals=2),
        _bots(players),
        ICLLogger(expected_log),
        show_play=False,
    )

    actual_log = tmp_path / "gui.jsonl"
    sink = Collector()
    config = SessionConfig(
        tuple(SeatConfig(SeatKind.SMART) for _ in range(players)), log_path=actual_log
    )
    runner = GameRunner(
        config, sink, pace=PaceControl(0), controllers=_bots(players), engine_factory=_factory(7, deals=2)
    )
    runner.start()
    done = sink.wait_finished()

    assert not done.aborted
    assert sink.of(DealFinished)[-1].totals == expected
    assert actual_log.read_text(encoding="utf-8") == expected_log.read_text(encoding="utf-8")


def test_event_stream_is_complete_and_ordered() -> None:
    sink = Collector()
    runner = GameRunner(
        _config(4), sink, pace=PaceControl(0), controllers=_bots(4, 0), engine_factory=_factory(1)
    )
    runner.start()
    sink.wait_finished()

    kinds = [type(e).__name__ for e in sink.events]
    assert kinds[0] == "SessionStarted" and kinds[1] == "DealStarted"
    assert kinds[-1] == "SessionFinished" and kinds[-2] == "DealFinished"
    assert len(sink.of(MovePlayed)) == 52 and len(sink.of(TurnStarted)) == 52
    assert len(sink.of(TrickCompleted)) == 13
    assert [m.move_number for m in sink.of(MovePlayed)] == list(range(1, 53))
    finished = sink.of(DealFinished)[0]
    assert finished.contract is GameContract.ROBBER
    assert sum(finished.scores.values()) == contract_total_penalty(GameContract.ROBBER, 4)
    last_trick = sink.of(TrickCompleted)[-1]
    assert len(last_trick.cards) == 4 and last_trick.snapshot.deal_over


def test_multiple_deals_accumulate_totals() -> None:
    sink = Collector()
    runner = GameRunner(
        _config(3), sink, pace=PaceControl(0), controllers=_bots(3, 0),
        engine_factory=_factory(5, deals=3),
    )
    runner.start()
    done = sink.wait_finished()

    assert done.deals_played == 3 and not done.aborted
    assert sum(done.totals.values()) == 3 * contract_total_penalty(GameContract.ROBBER, 3)
    assert [d.deal_number for d in sink.of(DealFinished)] == [19, 20, 21]
    assert [d.deal_number for d in sink.of(DealStarted)] == [19, 20, 21]
    assert sink.of(DealFinished)[-1].totals == done.totals


# ------------------------------------------------------------------ pacing


class Slow(FirstLegal):
    def __init__(self, seconds: float) -> None:
        self._seconds = seconds

    def select_move(self, observation: PlayerObservation) -> str:
        time.sleep(self._seconds)
        return super().select_move(observation)


def test_start_returns_immediately_with_a_slow_bot() -> None:
    sink = Collector()
    runner = GameRunner(
        _config(3), sink, pace=PaceControl(0), controllers={f"P{i}": Slow(0.4) for i in range(3)}
    )
    started = time.monotonic()
    runner.start()
    assert time.monotonic() - started < 0.1
    runner.abort()
    sink.wait_finished()


def test_pause_blocks_moves_and_step_allows_exactly_one() -> None:
    sink = Collector()
    pace = PaceControl(0, paused=True)
    runner = GameRunner(_config(3), sink, pace=pace, controllers=_bots(3, 0), engine_factory=_factory(2))
    runner.start()
    assert sink.wait_for(lambda: sink.of(TurnStarted))
    time.sleep(0.2)
    assert not sink.of(MovePlayed)

    pace.step()
    assert sink.wait_for(lambda: len(sink.of(MovePlayed)) == 1)
    time.sleep(0.2)
    assert len(sink.of(MovePlayed)) == 1

    pace.resume()
    done = sink.wait_finished()
    assert not done.aborted and len(sink.of(MovePlayed)) == 51
    assert sink.of(PauseChanged)[-1].paused is False


def test_pause_after_trick_stops_after_a_completed_trick() -> None:
    sink = Collector()
    pace = PaceControl(0, pause_after_trick=True)
    runner = GameRunner(_config(3), sink, pace=pace, controllers=_bots(3, 0), engine_factory=_factory(2))
    runner.start()
    assert sink.wait_for(lambda: sink.of(TrickCompleted))
    assert sink.wait_for(lambda: pace.paused)
    count = len(sink.of(MovePlayed))
    time.sleep(0.2)
    assert len(sink.of(MovePlayed)) == count
    assert count % 3 == 0
    pace.pause_after_trick = False
    pace.resume()
    sink.wait_finished()


def test_abort_while_paused_finishes_quickly() -> None:
    sink = Collector()
    runner = GameRunner(
        _config(3), sink, pace=PaceControl(0, paused=True), controllers=_bots(3, 0)
    )
    runner.start()
    assert sink.wait_for(lambda: sink.of(TurnStarted))
    runner.abort()
    done = sink.wait_finished(2.0)
    assert done.aborted and done.deals_played == 0
    assert runner.join(2.0)


def test_delay_spaces_bot_moves() -> None:
    sink = Collector()
    runner = GameRunner(
        _config(3), sink, pace=PaceControl(0.05), controllers={f"P{i}": FirstLegal() for i in range(3)}
    )
    started = time.monotonic()
    runner.start()
    assert sink.wait_for(lambda: len(sink.of(MovePlayed)) >= 5)
    assert time.monotonic() - started >= 4 * 0.05
    runner.abort()
    sink.wait_finished()


# -------------------------------------------------------------------- human


def test_human_seat_waits_for_a_legal_click() -> None:
    sink = Collector()
    config = SessionConfig(
        (SeatConfig(SeatKind.HUMAN), SeatConfig(SeatKind.SMART), SeatConfig(SeatKind.SMART)),
        log_path=None,
    )
    controllers = {
        "P0": HumanGuiController(),
        "P1": SmartHeartsBot(num_samples=0, seed=1),
        "P2": SmartHeartsBot(num_samples=0, seed=2),
    }
    runner = GameRunner(
        config, sink, pace=PaceControl(0), controllers=controllers, engine_factory=_factory(3)
    )
    human = runner.human_controller("P0")
    assert human is not None
    runner.start()

    def human_turns() -> list[TurnStarted]:
        return [t for t in sink.of(TurnStarted) if t.is_human]

    assert sink.wait_for(human_turns)  # bots may open the deal first
    turn = human_turns()[0]
    assert turn.snapshot.legal_moves
    assert sink.wait_for(lambda: human.awaiting_move)
    assert not human.submit("ZZ")
    assert not [m for m in sink.of(MovePlayed) if m.player_id == "P0"]

    legal = turn.snapshot.legal_moves[0]
    assert human.submit(legal)
    assert sink.wait_for(lambda: [m for m in sink.of(MovePlayed) if m.player_id == "P0"])
    move = [m for m in sink.of(MovePlayed) if m.player_id == "P0"][0]
    assert move.player_id == "P0" and move.card == legal and move.model_name == "human"
    runner.abort()
    sink.wait_finished()


def test_abort_releases_a_waiting_human() -> None:
    sink = Collector()
    config = SessionConfig((SeatConfig(SeatKind.HUMAN),) * 3, log_path=None)
    controllers = {f"P{i}": HumanGuiController() for i in range(3)}
    runner = GameRunner(
        config, sink, pace=PaceControl(0), controllers=controllers, engine_factory=_factory(3)
    )
    runner.start()
    assert sink.wait_for(lambda: sink.of(TurnStarted))
    runner.abort()
    assert sink.wait_finished(2.0).aborted


def test_multi_deal_session_with_a_human_pauses_between_deals() -> None:
    sink = Collector()
    config = SessionConfig(
        (SeatConfig(SeatKind.HUMAN), SeatConfig(SeatKind.SMART), SeatConfig(SeatKind.SMART)),
        log_path=None,
    )
    controllers = {
        "P0": HumanGuiController(),
        "P1": SmartHeartsBot(num_samples=0, seed=1),
        "P2": SmartHeartsBot(num_samples=0, seed=2),
    }
    runner = GameRunner(
        config, sink, pace=PaceControl(0), controllers=controllers,
        engine_factory=_factory(3, deals=2),
    )
    human = runner.human_controller("P0")
    assert human is not None
    runner.start()

    def play_human_turns() -> None:
        while not runner.pace.aborted and not sink.of(SessionFinished):
            if human.awaiting_move:
                turn = sink.of(TurnStarted)[-1]
                human.submit(turn.snapshot.legal_moves[0])
            time.sleep(0.005)

    threading.Thread(target=play_human_turns, daemon=True).start()
    assert sink.wait_for(lambda: sink.of(DealFinished))
    assert sink.wait_for(lambda: runner.pace.paused)  # waiting for the next deal
    assert len(sink.of(DealStarted)) == 1
    runner.pace.resume()
    done = sink.wait_finished()
    assert done.deals_played == 2


# ------------------------------------------------------------------- errors


class Boom(PlayerController):
    model_name = "boom"

    def __init__(self, failures: int) -> None:
        self.failures = failures

    def select_move(self, observation: PlayerObservation) -> str:
        if self.failures > 0:
            self.failures -= 1
            raise RuntimeError("no api key")
        return observation.legal_moves[0]


def _boom_runner(sink: Collector, failures: int) -> GameRunner:
    runner = GameRunner(
        _config(3), sink, pace=PaceControl(0),
        controllers={"P0": Boom(failures), "P1": FirstLegal(), "P2": FirstLegal()},
        engine_factory=_factory(4),
    )
    return runner


def test_controller_error_can_be_retried() -> None:
    sink = Collector()
    runner = _boom_runner(sink, failures=1)
    runner.start()
    assert sink.wait_for(lambda: sink.of(ControllerError))
    error = sink.of(ControllerError)[0]
    assert error.player_id == "P0" and "no api key" in error.message
    runner.resolve_error(ErrorResolution.RETRY)
    assert sink.wait_finished().aborted is False


def test_controller_error_can_swap_in_a_smart_bot() -> None:
    sink = Collector()
    runner = _boom_runner(sink, failures=10**6)
    runner.start()
    assert sink.wait_for(lambda: sink.of(ControllerError))
    runner.resolve_error(ErrorResolution.REPLACE_WITH_SMART)
    assert sink.wait_finished().aborted is False
    assert any("SmartHeartsBot" in n.text for n in sink.of(Notice))
    assert {m.model_name for m in sink.of(MovePlayed) if m.player_id == "P0"} == {"smart_bot"}


def test_controller_error_can_abort() -> None:
    sink = Collector()
    runner = _boom_runner(sink, failures=10**6)
    runner.start()
    assert sink.wait_for(lambda: sink.of(ControllerError))
    runner.resolve_error(ErrorResolution.ABORT)
    assert sink.wait_finished().aborted


def test_illegal_choice_is_reported_as_an_error() -> None:
    class Cheater(PlayerController):
        def select_move(self, observation: PlayerObservation) -> str:
            return "ZZ"

    sink = Collector()
    runner = GameRunner(
        _config(3), sink, pace=PaceControl(0),
        controllers={"P0": Cheater(), "P1": FirstLegal(), "P2": FirstLegal()},
        engine_factory=_factory(4),
    )
    runner.start()
    assert sink.wait_for(lambda: sink.of(ControllerError))
    assert "illegal move" in sink.of(ControllerError)[0].message
    runner.resolve_error(ErrorResolution.ABORT)
    sink.wait_finished()


# --------------------------------------------------------- analyzer & logging


def test_analyzer_receives_pre_move_state_and_result_is_attached() -> None:
    seen: list[AnalysisInput] = []

    def analyzer(data: AnalysisInput) -> str:
        seen.append(data)
        return f"{data.observation.player_id}:{data.chosen}"

    sink = Collector()
    runner = GameRunner(
        _config(3), sink, pace=PaceControl(0), controllers=_bots(3, 0),
        analyzer=analyzer, engine_factory=_factory(6),
    )
    runner.start()
    sink.wait_finished()

    moves = sink.of(MovePlayed)
    assert len(seen) == len(moves) == 51
    assert all(m.analysis == f"{m.player_id}:{m.card}" for m in moves)
    assert seen[0].history == () and len(seen[0].observation.hand) == 17
    # After three moves one trick is finished and visible to the analyzer.
    assert len(seen[3].history) == 1 and len(seen[3].history[0]) == 3


def test_analyzer_failure_does_not_stop_the_game() -> None:
    def broken(_: AnalysisInput) -> None:
        raise RuntimeError("x")

    sink = Collector()
    runner = GameRunner(
        _config(3), sink, pace=PaceControl(0), controllers=_bots(3, 0), analyzer=broken,
        engine_factory=_factory(6),
    )
    runner.start()
    done = sink.wait_finished()
    assert not done.aborted
    assert all(m.analysis is None for m in sink.of(MovePlayed))


def test_unwritable_log_disables_logging_with_a_notice(tmp_path: Path) -> None:
    blocker = tmp_path / "file"
    blocker.write_text("x")
    sink = Collector()
    config = SessionConfig((SeatConfig(SeatKind.SMART),) * 3, log_path=blocker / "log.jsonl")
    runner = GameRunner(
        config, sink, pace=PaceControl(0), controllers=_bots(3, 0), engine_factory=_factory(6)
    )
    runner.start()
    done = sink.wait_finished()
    assert not done.aborted
    assert len(sink.of(Notice)) == 1


def test_trajectory_log_records_every_move(tmp_path: Path) -> None:
    log = tmp_path / "t.jsonl"
    sink = Collector()
    config = SessionConfig((SeatConfig(SeatKind.SMART),) * 3, log_path=log)
    runner = GameRunner(
        config, sink, pace=PaceControl(0), controllers=_bots(3, 0), engine_factory=_factory(6)
    )
    runner.start()
    sink.wait_finished()
    assert len(log.read_text(encoding="utf-8").splitlines()) == 51
