"""Worker thread that plays a session: the GUI counterpart of ``main.play_deal`` / ``play_session``.

Only this thread touches the engine and the controllers. The UI receives
immutable events through ``sink`` and steers the thread through ``PaceControl``,
``HumanGuiController.submit`` and ``resolve_error``.
"""

from __future__ import annotations

import logging
import queue
import threading
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from enum import Enum
from typing import Any

from controllers.base import PlayerController
from engine.observation import PlayerObservation
from engine.state import GameState
from gui.core.controllers_factory import build_controller
from gui.core.events import (
    BotUnavailable,
    ControllerError,
    DealFinished,
    DealStarted,
    FatalError,
    GameEvent,
    MovePlayed,
    Notice,
    PauseChanged,
    SessionFinished,
    SessionStarted,
    TrickCompleted,
    TurnStarted,
)
from gui.core.ai_failures import classify_failure
from gui.core.human_controller import HumanGuiController, MoveCancelled
from gui.core.pace import PaceControl
from gui.core.seat_config import SeatConfig, SeatKind, SessionConfig
from gui.core.session import SessionStats
from gui.core.snapshot import snapshot_from_engine
from utils.icl_logger import ICLLogger

log = logging.getLogger(__name__)

EventSink = Callable[[GameEvent], None]
EngineFactory = Callable[[int], GameState]  # num_players -> a fresh match


class ErrorResolution(Enum):
    RETRY = "retry"
    REPLACE_WITH_SMART = "replace_with_smart"
    ABORT = "abort"


@dataclass(frozen=True)
class AnalysisInput:
    """State *before* a move, for the optional quality analyzer."""

    deal_number: int
    observation: PlayerObservation
    history: tuple[tuple[str, ...], ...]  # finished tricks, cards in the order they were played
    chosen: str
    model_name: str


Analyzer = Callable[[AnalysisInput], Any]


class GameRunner:
    def __init__(
        self,
        config: SessionConfig,
        sink: EventSink,
        *,
        pace: PaceControl | None = None,
        controllers: Mapping[str, PlayerController] | None = None,
        analyzer: Analyzer | None = None,
        engine_factory: EngineFactory | None = None,
    ) -> None:
        self.config = config
        self.pace = pace if pace is not None else PaceControl()
        self.pace.on_change = lambda paused: self._emit(PauseChanged(paused))
        self._sink = sink
        self._analyzer = analyzer
        self._engine_factory = engine_factory or self._default_engine
        self._logger = ICLLogger(config.log_path) if config.log_path else None
        self._controllers: dict[str, PlayerController] = (
            dict(controllers)
            if controllers is not None
            else {
                pid: build_controller(seat, pid, index)
                for index, (pid, seat) in enumerate(
                    zip(config.player_ids, config.seats, strict=True)
                )
            }
        )
        self._resolutions: queue.Queue[ErrorResolution] = queue.Queue()
        self._thread: threading.Thread | None = None

    # ------------------------------------------------------------- lifecycle

    def start(self) -> None:
        if self._thread is not None:
            raise RuntimeError("Runner already started")
        self._thread = threading.Thread(target=self._run, name="hearts-runner", daemon=True)
        self._thread.start()

    def abort(self) -> None:
        """Stop as soon as possible. A bot blocked in a network call finishes in the background."""
        self.pace.abort()
        for controller in self._controllers.values():
            if isinstance(controller, HumanGuiController):
                controller.cancel()
        self._resolutions.put(ErrorResolution.ABORT)

    def join(self, timeout: float | None = None) -> bool:
        """Wait for the thread; ``True`` when it has finished."""
        if self._thread is not None:
            self._thread.join(timeout)
        return not self.running

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def human_controller(self, player_id: str) -> HumanGuiController | None:
        controller = self._controllers.get(player_id)
        return controller if isinstance(controller, HumanGuiController) else None

    def resolve_error(self, resolution: ErrorResolution) -> None:
        self._resolutions.put(resolution)

    # ------------------------------------------------------------------ run

    def _default_engine(self, num_players: int) -> GameState:
        return GameState.new(num_players, seed=self.config.seed)

    def _emit(self, event: GameEvent) -> None:
        self._sink(event)

    def _seat_label(self, pid: str, seat: SeatConfig) -> str:
        return seat.display_name

    def _run(self) -> None:
        cfg = self.config
        stats = SessionStats(cfg.player_ids)
        aborted = False
        try:
            engine = self._engine_factory(cfg.num_players)
            engine.auto_advance = False  # the finished deal stays on the table until we move on
            self._emit(
                SessionStarted(
                    player_ids=cfg.player_ids,
                    seat_labels={
                        pid: self._seat_label(pid, seat)
                        for pid, seat in zip(cfg.player_ids, cfg.seats, strict=True)
                    },
                    total_deals=engine.total_deals,
                )
            )
            while True:
                deal = engine.deal_number
                self._emit(
                    DealStarted(deal, engine.total_deals, snapshot_from_engine(engine, deal))
                )
                scores = self._play_deal(engine, deal)
                if scores is None:
                    aborted = True
                    break
                stats.record(scores)
                self._emit(
                    DealFinished(
                        deal_number=deal,
                        scores=scores,
                        contract=engine.current_contract,
                        declarer=engine.declarer,
                        totals=dict(stats.totals),
                        wins=dict(stats.wins),
                        ties=stats.ties,
                    )
                )
                if engine.is_over:
                    break
                if cfg.has_human:
                    # Show the result until the player presses "resume" (next deal).
                    self.pace.pause()
                    proceed = self.pace.gate_before() is not None
                else:
                    proceed = self.pace.trick_hold()
                if not proceed:
                    aborted = True
                    break
                engine.start_next_deal()
        except Exception as exc:  # the UI must learn about a crashed thread
            log.exception("Runner crashed")
            aborted = True
            self._emit(FatalError(f"{type(exc).__name__}: {exc}"))
        finally:
            self._emit(
                SessionFinished(
                    totals=dict(stats.totals),
                    wins=dict(stats.wins),
                    ties=stats.ties,
                    deals_played=stats.deals_played,
                    winners=tuple(stats.leaders) if stats.deals_played else (),
                    aborted=aborted,
                )
            )

    def _play_deal(self, engine: GameState, deal: int) -> dict[str, int] | None:
        """Play one deal. ``None`` when aborted."""
        pace = self.pace
        tricks: list[tuple[str, ...]] = []
        move_number = 0
        last_move_at = time.monotonic()

        while not (engine.deal_finished or engine.is_over):
            if pace.aborted:
                return None
            pid = engine.current_player
            assert pid is not None
            observation = engine.get_player_observation(pid)
            human = isinstance(self._controllers[pid], HumanGuiController)
            self._emit(TurnStarted(pid, human, snapshot_from_engine(engine, deal)))

            stepped = False
            if not human:
                gate = pace.gate_before()
                if gate is None:
                    return None
                stepped = gate

            started = pace.clock()  # stands still while paused: a pause is not thinking time
            chosen = self._decide(pid, observation)
            if chosen is None:
                return None
            think_seconds = pace.clock() - started
            controller = self._controllers[pid]

            analysis = self._analyze(deal, observation, tricks, chosen, controller)
            if not human and not pace.gate_after(last_move_at, stepped=stepped):
                return None

            self._log_move(observation, chosen, controller)
            result = engine.play_card(pid, chosen)
            move_number += 1
            snapshot = snapshot_from_engine(engine, deal)
            self._emit(
                MovePlayed(
                    deal_number=deal,
                    move_number=move_number,
                    player_id=pid,
                    card=chosen,
                    model_name=controller.model_name,
                    think_seconds=think_seconds,
                    reasoning=controller.last_reasoning,
                    result=result,
                    snapshot=snapshot,
                    analysis=analysis,
                )
            )
            last_move_at = time.monotonic()

            if result.trick_completed:
                cards = (*observation.current_trick, (pid, chosen))
                tricks.append(tuple(card for _, card in cards))
                assert result.trick_winner is not None
                self._emit(
                    TrickCompleted(
                        deal_number=deal,
                        trick_number=len(tricks),
                        cards=cards,
                        winner=result.trick_winner,
                        points=result.trick_points,
                        snapshot=snapshot,
                    )
                )
                if not result.deal_over:
                    pace.after_trick()
                if not pace.trick_hold():  # the last trick stays visible too
                    return None
                last_move_at = time.monotonic()

        return dict(engine.scores)

    # ---------------------------------------------------------------- helpers

    def _decide(self, pid: str, observation: PlayerObservation) -> str | None:
        """Ask the seat's controller; on failure let the user choose what happens."""
        while True:
            controller = self._controllers[pid]
            try:
                chosen = controller.select_move(observation)
                if chosen not in observation.legal_moves:
                    raise ValueError(f"{pid} chose illegal move {chosen!r}")
                if self._api_gave_up(pid, controller):
                    return None  # the stand-in card of a failed request is not played
                return chosen
            except MoveCancelled:
                return None
            except Exception as exc:
                if self.pace.aborted:
                    return None
                log.warning("Controller of %s failed: %s", pid, exc)
                resolution = self._ask_user(pid, exc)
                if resolution is ErrorResolution.ABORT:
                    return None
                if resolution is ErrorResolution.REPLACE_WITH_SMART:
                    index = self.config.player_ids.index(pid)
                    replacement = SeatConfig(
                        SeatKind.SMART, smart_samples=self.config.seats[index].smart_samples
                    )
                    self._controllers[pid] = build_controller(replacement, pid, index)
                    self._emit(Notice(f"{pid}: zastąpiony przez SmartHeartsBot."))

    def _api_gave_up(self, pid: str, controller: PlayerController) -> bool:
        """``True`` when the bot's request failed for good (no tokens, no access): game over.

        ``AIBot`` swallows API errors and plays the first legal card; its
        ``last_reasoning`` is the only trace. Short rate limits just raise a notice.
        """
        failure = classify_failure(getattr(controller, "last_reasoning", ""))
        if failure is None:
            return False
        label = self._seat_label(pid, self.config.seats[self.config.player_ids.index(pid)])
        if not failure.fatal:
            self._emit(Notice(f"{pid} ({label}): limit zapytań API, zagrano ruch zastępczy."))
            return False
        self._emit(BotUnavailable(pid, label, failure.kind, failure.message))
        self.pace.abort()
        return True

    def _ask_user(self, pid: str, exc: Exception) -> ErrorResolution:
        while not self._resolutions.empty():
            self._resolutions.get_nowait()
        index = self.config.player_ids.index(pid)
        self._emit(
            ControllerError(
                player_id=pid,
                seat_label=self._seat_label(pid, self.config.seats[index]),
                message=f"{type(exc).__name__}: {exc}",
            )
        )
        while True:
            if self.pace.aborted:
                return ErrorResolution.ABORT
            try:
                return self._resolutions.get(timeout=0.05)
            except queue.Empty:
                continue

    def _analyze(
        self,
        deal: int,
        observation: PlayerObservation,
        tricks: list[tuple[str, ...]],
        chosen: str,
        controller: PlayerController,
    ) -> Any | None:
        if self._analyzer is None:
            return None
        try:
            return self._analyzer(
                AnalysisInput(deal, observation, tuple(tricks), chosen, controller.model_name)
            )
        except Exception:  # analysis must never stop a game
            log.exception("Move analysis failed")
            return None

    def _log_move(
        self, observation: PlayerObservation, chosen: str, controller: PlayerController
    ) -> None:
        """Same record as ``main.play_deal`` writes to ``logs/trajectories.jsonl``."""
        if self._logger is None:
            return
        try:
            self._logger.log(observation, chosen, controller.last_reasoning, controller.model_name)
        except OSError as exc:
            self._logger = None
            self._emit(Notice(f"Nie można zapisać logu ruchów ({exc}); logowanie wyłączone."))
