"""Thread-safe event sink for tests that drive a ``GameRunner`` directly."""

from __future__ import annotations

import threading
import time

from gui.core.events import GameEvent, SessionFinished


class Collector:
    """Collects runner events and lets a test wait for a condition."""

    def __init__(self) -> None:
        self.events: list[GameEvent] = []
        self._lock = threading.Lock()

    def __call__(self, event: GameEvent) -> None:
        with self._lock:
            self.events.append(event)

    def of(self, kind: type) -> list:
        with self._lock:
            return [e for e in self.events if isinstance(e, kind)]

    def wait_for(self, predicate, timeout: float = 5.0) -> bool:  # type: ignore[no-untyped-def]
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if predicate():
                return True
            time.sleep(0.01)
        return False

    def wait_finished(self, timeout: float = 10.0) -> SessionFinished:
        assert self.wait_for(lambda: self.of(SessionFinished), timeout), "session did not finish"
        return self.of(SessionFinished)[0]
