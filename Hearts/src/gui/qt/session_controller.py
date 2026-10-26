"""One running session as seen by the widgets: runner + pacing + event delivery."""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import QObject, Signal

from gui.config import DEFAULT_DELAY_S
from gui.core.game_runner import Analyzer, ErrorResolution, GameRunner
from gui.core.pace import PaceControl
from gui.core.seat_config import SessionConfig
from gui.qt.bridge import QtBridge


class SessionController(QObject):
    eventsReady = Signal(list)

    def __init__(
        self,
        config: SessionConfig,
        parent: QObject | None = None,
        *,
        analyzer: Analyzer | None = None,
        **runner_options: Any,  # controllers=..., engine_factory=... (tests)
    ) -> None:
        super().__init__(parent)
        self.config = config
        self.analyzer = analyzer  # the live evaluator, when the session has one
        # Without a human a slow default would only make a spectator wait.
        self.pace = PaceControl(DEFAULT_DELAY_S)
        self._bridge = QtBridge(self)
        self._bridge.eventsReady.connect(self.eventsReady)
        self.runner = GameRunner(
            config, self._bridge.push, pace=self.pace, analyzer=analyzer, **runner_options
        )

    def start(self) -> None:
        self.runner.start()

    def submit_card(self, player_id: str, card: str) -> bool:
        controller = self.runner.human_controller(player_id)
        return controller is not None and controller.submit(card)

    def resolve_error(self, resolution: ErrorResolution) -> None:
        self.runner.resolve_error(resolution)

    def close(self) -> None:
        """Abort and detach: the UI stops hearing from this runner immediately."""
        self.runner.abort()
        self._bridge.close()
