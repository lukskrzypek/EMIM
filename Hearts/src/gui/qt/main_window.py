"""Main window: lobby <-> game <-> quality report."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtGui import QCloseEvent, QKeySequence, QShortcut
from PySide6.QtWidgets import QMainWindow, QStackedWidget

from gui.config import IGNORED_PLAYERS, LOG_PATH
from gui.core.live_evaluator import LiveEvaluator
from gui.core.seat_config import SessionConfig
from gui.qt.game_view import GameView
from gui.qt.lobby.lobby_view import LobbyView
from gui.qt.report.report_view import ReportView
from gui.qt.session_controller import SessionController
from gui.qt.settings import AppSettings
from gui.qt.table.renderer_factory import default_renderer


class MainWindow(QMainWindow):
    def __init__(
        self, settings: AppSettings | None = None, *, log_path: Path = LOG_PATH
    ) -> None:
        super().__init__()
        self.settings = settings if settings is not None else AppSettings()
        self.setWindowTitle("Kierki")
        self.resize(1360, 860)
        geometry = self.settings.geometry()
        if geometry is not None:
            self.restoreGeometry(geometry)
        self.stack = QStackedWidget()
        self.setCentralWidget(self.stack)

        self.lobby = LobbyView()
        self.lobby.apply_state(self.settings.lobby_state())
        self.lobby.startRequested.connect(self.start_session)
        self.lobby.reportRequested.connect(self.show_report)
        self.stack.addWidget(self.lobby)

        self.report = ReportView(log_path, ignored_default=IGNORED_PLAYERS, settings=self.settings)
        self.report.backRequested.connect(self.show_lobby)
        self.stack.addWidget(self.report)

        self.session: SessionController | None = None
        self.game: GameView | None = None
        self.config: SessionConfig | None = None

        self._fullscreen_shortcut = QShortcut(QKeySequence("F11"), self)
        self._fullscreen_shortcut.activated.connect(self.toggle_fullscreen)

    def start_session(self, config: SessionConfig) -> None:
        self._drop_session()
        self.settings.save_lobby_state(self.lobby.state())
        session = SessionController(config, self, analyzer=LiveEvaluator())
        game = GameView(session, settings=self.settings, renderer=default_renderer())
        game.backRequested.connect(self.show_lobby)
        # A bound method, not a lambda: a lambda closing over the window crashed PySide when the
        # view was deleted before the event loop had run.
        game.rematchRequested.connect(self.rematch)
        self.config = config
        self.session, self.game = session, game
        self.stack.addWidget(game)
        self.stack.setCurrentWidget(game)
        session.start()

    def rematch(self) -> None:
        """Play again with the same seats (the config of the session that just ended)."""
        if self.config is not None:
            self.start_session(self.config)

    def show_lobby(self) -> None:
        self._drop_session()
        self.lobby.refresh()
        self.stack.setCurrentWidget(self.lobby)

    def show_report(self) -> None:
        self._drop_session()
        self.stack.setCurrentWidget(self.report)
        self.report.refresh()

    def toggle_fullscreen(self) -> None:
        if self.isFullScreen():
            self.showNormal()
        else:
            self.showFullScreen()

    def _drop_session(self) -> None:
        if self.session is not None:
            self.session.close()
            self.session.deleteLater()
        if self.game is not None:
            self.stack.removeWidget(self.game)
            self.game.deleteLater()
        self.session = self.game = None

    def closeEvent(self, event: QCloseEvent) -> None:
        self._drop_session()
        self.settings.save_lobby_state(self.lobby.state())
        self.settings.save_geometry(self.saveGeometry())
        super().closeEvent(event)
