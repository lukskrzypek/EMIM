"""A human seat for the GUI: ``select_move`` blocks the worker thread, never the UI."""

from __future__ import annotations

import queue
import threading

from controllers.base import PlayerController
from engine.game import PlayerObservation


class MoveCancelled(Exception):
    """Raised inside ``select_move`` when the game is aborted while waiting for a click."""


class HumanGuiController(PlayerController):
    """Waits until the UI calls :meth:`submit` with one of the legal cards."""

    model_name = "human"

    def __init__(self, poll_interval: float = 0.05) -> None:
        self._poll = poll_interval
        self._answers: queue.Queue[str] = queue.Queue()
        self._lock = threading.Lock()
        self._awaiting: frozenset[str] = frozenset()
        self._cancelled = threading.Event()

    @property
    def awaiting_move(self) -> bool:
        with self._lock:
            return bool(self._awaiting)

    def submit(self, card: str) -> bool:
        """Offer a card from any thread. ``False`` if it is not a currently legal move."""
        with self._lock:
            if card not in self._awaiting:
                return False
            self._awaiting = frozenset()
        self._answers.put(card)
        return True

    def cancel(self) -> None:
        self._cancelled.set()

    def select_move(self, observation: PlayerObservation) -> str:
        if not observation.legal_moves:
            raise ValueError(f"{observation.player_id} has no legal moves")
        with self._lock:
            while not self._answers.empty():  # drop a stale click from an earlier turn
                self._answers.get_nowait()
            self._awaiting = frozenset(observation.legal_moves)
        try:
            while True:
                if self._cancelled.is_set():
                    raise MoveCancelled
                try:
                    return self._answers.get(timeout=self._poll)
                except queue.Empty:
                    continue
        finally:
            with self._lock:
                self._awaiting = frozenset()
