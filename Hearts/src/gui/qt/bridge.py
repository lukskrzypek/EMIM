"""Thread-safe hand-over of runner events to the Qt main loop."""

from __future__ import annotations

import queue

from PySide6.QtCore import QObject, QTimer, Signal

from gui.core.events import GameEvent

DRAIN_INTERVAL_MS = 30


class QtBridge(QObject):
    """``push`` may be called from any thread; ``eventsReady`` fires in the GUI thread.

    Events are collected and delivered in batches every ``DRAIN_INTERVAL_MS``, so a
    runner at full speed cannot flood the event loop: the UI repaints once per batch.
    """

    eventsReady = Signal(list)

    def __init__(self, parent: QObject | None = None, interval_ms: int = DRAIN_INTERVAL_MS) -> None:
        super().__init__(parent)
        self._queue: queue.SimpleQueue[GameEvent] = queue.SimpleQueue()
        self._closed = False
        self._timer = QTimer(self)
        self._timer.setInterval(interval_ms)
        self._timer.timeout.connect(self.drain)
        self._timer.start()

    def push(self, event: GameEvent) -> None:
        if not self._closed:
            self._queue.put(event)

    def drain(self) -> None:
        batch: list[GameEvent] = []
        while True:
            try:
                batch.append(self._queue.get_nowait())
            except queue.Empty:
                break
        if batch and not self._closed:
            self.eventsReady.emit(batch)

    def close(self) -> None:
        """Stop delivering. Late events of an abandoned runner are dropped."""
        self._closed = True
        self._timer.stop()
