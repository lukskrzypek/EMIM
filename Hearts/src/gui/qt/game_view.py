"""Game screen: painted table, tempo controls, scores and log."""

from __future__ import annotations

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QCheckBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSplitter,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from utils.contract_text import contract_label
from gui.core.events import (
    BotUnavailable,
    ControllerError,
    DealFinished,
    DealStarted,
    GameEvent,
    MovePlayed,
    PauseChanged,
    SessionFinished,
    SessionStarted,
    TurnStarted,
)
from gui.core.game_runner import ErrorResolution
from gui.core.ai_failures import HEADLINES, REASONS
from gui.core.live_evaluator import LiveEvaluator, hint_for_table
from gui.core.seat_config import SeatKind
from gui.core.table_model import TableModel
from gui.qt.control_bar import ControlBar
from gui.qt.quality.insight_panel import BotInsightPanel
from gui.qt.quality.quality_panel import QualityPanel
from gui.qt.session_controller import SessionController
from gui.qt.settings import AppSettings, ViewPrefs
from gui.qt.table.card_renderer import CardRenderer
from gui.qt.table.scoreboard import ScoreboardWidget, TrickLogWidget
from gui.qt.table.table_scene import TableScene
from gui.qt.table.table_view import TableView
from gui.qt.table.vector_card_renderer import VectorCardRenderer

MAX_ANIMATED_STEPS = 4  # a batch with more moves than this is a fast-forward: no gliding


class GameView(QWidget):
    backRequested = Signal()
    rematchRequested = Signal()

    def __init__(
        self,
        session: SessionController,
        parent: QWidget | None = None,
        *,
        renderer: CardRenderer | None = None,
        settings: AppSettings | None = None,
    ) -> None:
        super().__init__(parent)
        self.session = session
        self.settings = settings
        config = session.config
        self._finished = False
        self.last_failure_box: QMessageBox | None = None
        self._restoring = True  # no saving while the stored preferences are applied

        prefs = settings.view_prefs() if settings is not None else None
        self._stored_four_color = prefs.four_color if prefs is not None else False
        if prefs is not None:
            if prefs.delay is not None:
                session.pace.delay = prefs.delay
            session.pace.pause_after_trick = prefs.after_trick

        self.model = TableModel(config.player_ids, config.human_ids, clock=session.pace.clock)
        self.renderer: CardRenderer = renderer or VectorCardRenderer()
        self.table_scene = TableScene(self.model, self.renderer)
        self.table = TableView(self.table_scene)
        self.scoreboard = ScoreboardWidget()
        self.log = TrickLogWidget()
        self.controls = ControlBar(session.pace)

        self.status = QLabel("Start…")
        self.status.setObjectName("subtitle")
        self.reveal = QCheckBox("Pokaż karty botów")
        if config.has_human:
            self.reveal.setToolTip("Podgląd rąk botów (tryb 'god view')")
        else:
            self.reveal.setChecked(True)
            self.reveal.setEnabled(False)
            self.reveal.setText("Karty widoczne (grają same boty)")
            self.model.reveal_bots = True
        self.four_color = QCheckBox("Talia 4-kolorowa")
        self.four_color.setEnabled(isinstance(self.renderer, VectorCardRenderer))
        self.back_button = QPushButton("Wróć do lobby")
        self.back_button.setObjectName("danger")

        header = QHBoxLayout()
        header.addWidget(self.status, 1)
        header.addWidget(self.reveal)
        header.addWidget(self.four_color)
        header.addWidget(self.back_button)

        labels = {
            pid: seat.display_name for pid, seat in zip(config.player_ids, config.seats, strict=True)
        }
        evaluator = session.analyzer if isinstance(session.analyzer, LiveEvaluator) else None
        memory_models = {  # the AI seats: only their bots keep a memory pad (key = file name part)
            pid: seat.memory_key
            for pid, seat in zip(config.player_ids, config.seats, strict=True)
            if seat.kind is SeatKind.AI
        }
        self.quality_panel = QualityPanel(
            labels, has_human=config.has_human, evaluator=evaluator, memory_models=memory_models
        )
        self.insight = BotInsightPanel(labels, config.human_ids, memory_models=memory_models)
        quality_scroll = QScrollArea()
        quality_scroll.setWidgetResizable(True)
        quality_scroll.setFrameShape(QFrame.Shape.NoFrame)
        quality_scroll.setWidget(self.quality_panel)

        tabs = QTabWidget()
        tabs.addTab(self.scoreboard, "Wyniki")
        tabs.addTab(quality_scroll, "Jakość")
        tabs.addTab(self.insight, "Bot")
        tabs.addTab(self.log, "Log")
        self.tabs = tabs
        splitter = QSplitter()
        splitter.addWidget(self.table)
        splitter.addWidget(tabs)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)
        splitter.setSizes([780, 480])
        tabs.setMinimumWidth(400)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.addLayout(header)
        layout.addWidget(self.controls)
        layout.addWidget(splitter, 1)

        self.back_button.clicked.connect(self.backRequested)
        self.reveal.toggled.connect(self._on_reveal)
        self.four_color.toggled.connect(self._on_four_color)
        self.quality_panel.hintsToggled.connect(lambda _: self._update_hint())
        self.quality_panel.paramsChanged.connect(self._update_hint)
        self.table.cardClicked.connect(self._on_card_clicked)
        self.table.veilAcknowledged.connect(self._on_veil_ack)
        self.table.result.nextDealRequested.connect(self._on_next_deal)
        self.table.result.lobbyRequested.connect(self.backRequested)
        self.table.result.rematchRequested.connect(self.rematchRequested)
        session.eventsReady.connect(self.handle_events)

        self._install_shortcuts()
        if prefs is not None:
            self._apply_prefs(prefs)
        self._restoring = False
        for signal in (
            self.reveal.toggled,
            self.four_color.toggled,
            self.quality_panel.hint_check.toggled,
            self.quality_panel.live_check.toggled,
            self.controls.after_trick.toggled,
            self.controls.speed.valueChanged,
        ):
            signal.connect(self._save_prefs)

        self._clock = QTimer(self)  # keeps the "thinking… 1.2 s" label alive
        self._clock.setInterval(200)
        self._clock.timeout.connect(self._tick)
        self._clock.start()

    # ------------------------------------------------- preferences, shortcuts

    def _apply_prefs(self, prefs: ViewPrefs) -> None:
        if self.four_color.isEnabled():
            self.four_color.setChecked(prefs.four_color)
        if self.session.config.has_human:
            self.reveal.setChecked(prefs.reveal_bots)
            self.quality_panel.hint_check.setChecked(prefs.hints)
        if self.quality_panel.live_check.isEnabled():
            self.quality_panel.live_check.setChecked(prefs.live_eval)

    def current_prefs(self) -> ViewPrefs:
        return ViewPrefs(
            # a PNG deck has no 4-colour mode: keep the stored choice for the next vector game
            four_color=self.four_color.isChecked() if self.four_color.isEnabled() else self._stored_four_color,
            reveal_bots=self.reveal.isChecked() and self.reveal.isEnabled(),
            hints=self.quality_panel.hint_check.isChecked(),
            live_eval=self.quality_panel.live_check.isChecked(),
            after_trick=self.controls.after_trick.isChecked(),
            delay=self.session.pace.delay,
        )

    def _save_prefs(self, *_: object) -> None:
        if self.settings is not None and not self._restoring:
            self.settings.save_view_prefs(self.current_prefs())

    def _install_shortcuts(self) -> None:
        """Space pauses, N steps, +/- change the tempo, Ctrl+1..4 switch tabs.

        Arrow keys are left alone: lists and the slider need them."""
        context = Qt.ShortcutContext.WidgetWithChildrenShortcut
        speed = self.controls.speed
        bindings = [
            (Qt.Key.Key_Space, self._shortcut_pause),
            (Qt.Key.Key_N, self._shortcut_step),
            (Qt.Key.Key_Plus, lambda: speed.setValue(speed.value() + 1)),
            (Qt.Key.Key_Equal, lambda: speed.setValue(speed.value() + 1)),  # '+' without Shift
            (Qt.Key.Key_Minus, lambda: speed.setValue(speed.value() - 1)),
        ]
        for index in range(self.tabs.count()):
            bindings.append(
                (Qt.Modifier.CTRL | Qt.Key(Qt.Key.Key_1 + index), lambda i=index: self.tabs.setCurrentIndex(i))
            )
        self.shortcuts: list[QShortcut] = []
        for key, handler in bindings:
            shortcut = QShortcut(QKeySequence(key), self)
            shortcut.setContext(context)
            shortcut.activated.connect(handler)
            self.shortcuts.append(shortcut)
        self.controls.pause_button.setToolTip("Pauza / wznów (Spacja)")
        self.controls.step_button.setToolTip("Wykonaj jeden ruch w pauzie (N)")
        speed.setToolTip("Tempo gry (+ szybciej, − wolniej)")

    def _shortcut_pause(self) -> None:
        if not self._finished:
            self.session.pace.toggle()

    def _shortcut_step(self) -> None:
        if not self._finished and self.session.pace.paused:
            self.session.pace.step()

    # ----------------------------------------------------------------- events

    def handle_events(self, events: list[GameEvent]) -> None:
        new_deal = False
        steps = 0
        for event in events:
            self.model.apply(event)
            self.log.handle(event)
            if isinstance(event, (MovePlayed, TurnStarted)):
                steps += 1
            if isinstance(event, DealStarted):
                new_deal = True
            self._handle(event)

        pace = self.session.pace
        animate = pace.delay > 0 and steps <= MAX_ANIMATED_STEPS
        self.table_scene.animation_ms = int(min(450, max(120, pace.delay * 450)))
        if new_deal:
            self.table_scene.reset_deal(animate)
        else:
            self.table_scene.refresh(animate)
        self.quality_panel.apply(events)
        self.insight.apply(events)
        self._update_veil()
        self._update_hint()

    def _update_hint(self) -> None:
        """Rate the human's options before the move (never for a hand behind the veil)."""
        player = self.model.interactive_player
        hint = None
        if player is not None and self.quality_panel.hints_enabled:
            evaluator = self.quality_panel.evaluator
            hint = hint_for_table(self.model, player, evaluator.params if evaluator else None)
        self.quality_panel.set_hint(hint)

    def _handle(self, event: GameEvent) -> None:
        if isinstance(event, SessionStarted):
            self.scoreboard.configure(event.seat_labels)
        elif isinstance(event, DealStarted):
            self.table.result.hide()
            self.scoreboard.show_scores(event.snapshot.points, None)
        elif isinstance(event, TurnStarted):
            snap = event.snapshot
            actor = "twój ruch" if event.is_human else "myśli"
            self.status.setText(
                f"Rozdanie {snap.deal_number}/{snap.total_deals} · {contract_label(snap.contract)} · "
                f"lewa {snap.trick_number}/{snap.total_tricks} · {actor}: {event.player_id}"
            )
        elif isinstance(event, MovePlayed):
            self.scoreboard.show_scores(event.snapshot.points, event.snapshot.current_player)
        elif isinstance(event, DealFinished):
            self.scoreboard.record_deal(event)
            if event.deal_number < self.model.total_deals:
                self.table.result.show_deal(
                    event,
                    self.model.seat_labels,
                    can_continue=self.session.config.has_human,
                    waiting=not self.session.config.has_human,
                )
        elif isinstance(event, SessionFinished):
            self._finished = True
            self.controls.set_enabled_for_session(False)
            winners = ", ".join(event.winners) or "-"
            self.status.setText("Przerwano" if event.aborted else f"Koniec gry, prowadzi: {winners}")
            self.table.result.show_session(event, self.model.seat_labels)
        elif isinstance(event, PauseChanged):
            if not self._finished:
                self.controls.set_paused(event.paused)
        elif isinstance(event, ControllerError):
            QTimer.singleShot(0, lambda e=event: self._ask_error_resolution(e))
        elif isinstance(event, BotUnavailable):
            self.status.setText(HEADLINES.get(event.reason, "Bot niedostępny"))
            QTimer.singleShot(0, lambda e=event: self._tell_bot_unavailable(e))

    # ---------------------------------------------------------------- actions

    def _on_card_clicked(self, code: str) -> None:
        player = self.model.interactive_player
        if player is not None:
            self.session.submit_card(player, code)

    def _on_veil_ack(self) -> None:
        self.model.acknowledge_veil()
        self.table.veil.hide()
        self.table_scene.refresh(self.session.pace.delay > 0)
        self._update_hint()

    def _on_next_deal(self) -> None:
        self.table.result.hide()
        self.session.pace.resume()

    def _on_reveal(self, checked: bool) -> None:
        self.model.reveal_bots = checked
        self.table_scene.refresh(self.session.pace.delay > 0)

    def _on_four_color(self, checked: bool) -> None:
        if isinstance(self.renderer, VectorCardRenderer):
            self.renderer.set_four_color(checked)
            self.table_scene.update()

    def _update_veil(self) -> None:
        if self.model.veil_for is not None:
            self.table.veil.show_for(self.model.veil_for)
        else:
            self.table.veil.hide()

    def _tick(self) -> None:
        if self.model.thinking_since is not None:
            self.table_scene.refresh_plates()

    def _ask_error_resolution(self, error: ControllerError) -> None:
        if self._finished:
            return
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Warning)
        box.setWindowTitle("Błąd gracza")
        box.setText(f"{error.player_id} ({error.seat_label}) nie wykonał ruchu.")
        box.setInformativeText(error.message)
        retry = box.addButton("Ponów", QMessageBox.ButtonRole.AcceptRole)
        smart = box.addButton("Zastąp SmartHeartsBot", QMessageBox.ButtonRole.ActionRole)
        abort = box.addButton("Przerwij", QMessageBox.ButtonRole.RejectRole)
        box.exec()
        clicked = box.clickedButton()
        if clicked is retry:
            self.session.resolve_error(ErrorResolution.RETRY)
        elif clicked is smart:
            self.session.resolve_error(ErrorResolution.REPLACE_WITH_SMART)
        elif clicked is abort or clicked is None:
            self.session.resolve_error(ErrorResolution.ABORT)

    def _tell_bot_unavailable(self, failure: BotUnavailable) -> None:
        """No tokens (or no access): the game has already been stopped, just say why."""
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Critical)
        box.setWindowTitle(HEADLINES.get(failure.reason, "Bot niedostępny"))
        reason = REASONS.get(failure.reason, failure.reason)
        box.setText(
            f"{failure.player_id} ({failure.seat_label}) nie może dalej grać: {reason}.\n\n"
            "Gra została zakończona."
        )
        box.setInformativeText(failure.message)
        box.setStandardButtons(QMessageBox.StandardButton.Ok)
        self.last_failure_box = box  # kept for tests
        box.exec()

    def closeEvent(self, event) -> None:  # type: ignore[no-untyped-def]
        self._clock.stop()
        super().closeEvent(event)
