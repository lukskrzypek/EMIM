"""Side tables: scores per seat and the move / trick log."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QHeaderView,
    QListWidget,
    QListWidgetItem,
    QTableWidget,
    QTableWidgetItem,
)

from gui.core.cardtext import pretty_card
from utils.contract_text import contract_label
from gui.core.events import (
    BotUnavailable,
    DealFinished,
    DealStarted,
    FatalError,
    GameEvent,
    MovePlayed,
    Notice,
    SessionFinished,
    SessionStarted,
    TrickCompleted,
)
from gui.core.ai_failures import REASONS
from gui.qt.theme import ACCENT, TEXT_MUTED, enable_wrapping

COLUMNS = ("Gracz", "Kontroler", "Rozdanie", "Suma", "Wygrane")
MAX_LOG_ITEMS = 3000


class ScoreboardWidget(QTableWidget):
    def __init__(self) -> None:
        super().__init__(0, len(COLUMNS))
        self.setHorizontalHeaderLabels(COLUMNS)
        self.verticalHeader().hide()
        self.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
        header = self.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.labels: dict[str, str] = {}
        self.totals: dict[str, int] = {}
        self.wins: dict[str, int] = {}

    def configure(self, labels: dict[str, str]) -> None:
        self.labels = dict(labels)
        self.totals = dict.fromkeys(labels, 0)
        self.wins = dict.fromkeys(labels, 0)
        self.setRowCount(len(labels))
        self.show_scores({}, None)

    def record_deal(self, event: DealFinished) -> None:
        self.totals, self.wins = dict(event.totals), dict(event.wins)
        self.show_scores(event.scores, None)

    def show_scores(self, deal_points: dict[str, int], current: str | None) -> None:
        for row, pid in enumerate(self.labels):
            cells = (
                pid,
                self.labels[pid],
                str(deal_points.get(pid, 0)),
                str(self.totals.get(pid, 0)),
                str(self.wins.get(pid, 0)),
            )
            for col, text in enumerate(cells):
                item = QTableWidgetItem(text)
                if col > 1:
                    item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                if pid == current:
                    item.setForeground(QColor(ACCENT))
                self.setItem(row, col, item)


class TrickLogWidget(QListWidget):
    """Chronological log; the same lines go to the quality panel later."""

    def __init__(self) -> None:
        super().__init__()
        enable_wrapping(self)  # long reasoning lines continue below instead of scrolling sideways
        self.labels: dict[str, str] = {}

    def add_line(self, text: str, *, muted: bool = False) -> None:
        item = QListWidgetItem(text)
        if muted:
            item.setForeground(QColor(TEXT_MUTED))
        self.addItem(item)
        while self.count() > MAX_LOG_ITEMS:
            self.takeItem(0)
        self.scrollToBottom()

    def handle(self, event: GameEvent) -> None:
        if isinstance(event, SessionStarted):
            self.labels = dict(event.seat_labels)
            self.add_line(f"Sesja: {event.total_deals} rozdań", muted=True)
        elif isinstance(event, DealStarted):
            contract = contract_label(event.snapshot.contract)
            self.add_line(
                f"── Rozdanie {event.deal_number}/{event.total_deals}: {contract}, "
                f"rozdaje {event.snapshot.declarer} ──",
                muted=True,
            )
        elif isinstance(event, MovePlayed):
            who = f"{event.player_id} ({self.labels.get(event.player_id, '?')})"
            verdict = ""
            chosen = getattr(event.analysis, "chosen_eval", None)  # quality system, when enabled
            if chosen is not None:
                verdict = f"   {chosen.verdict} {chosen.correctness:.0f}"
            self.add_line(f"{who} → {pretty_card(event.card)}   [{event.think_seconds:.2f} s]{verdict}")
            if event.reasoning:
                self.add_line(f"      {event.reasoning}", muted=True)
        elif isinstance(event, TrickCompleted):
            plays = "  ".join(f"{p}:{pretty_card(c)}" for p, c in event.cards)
            self.add_line(
                f"   Lewa {event.trick_number}: {plays} → bierze {event.winner} (+{event.points} pkt)",
                muted=True,
            )
        elif isinstance(event, DealFinished):
            scores = "  ".join(f"{p}={s}" for p, s in event.scores.items())
            self.add_line(
                f"Koniec rozdania {event.deal_number} ({contract_label(event.contract)}): {scores}"
            )
        elif isinstance(event, SessionFinished):
            self.add_line("Przerwano" if event.aborted else "Koniec sesji")
        elif isinstance(event, Notice):
            self.add_line(f"ℹ {event.text}", muted=True)
        elif isinstance(event, BotUnavailable):
            reason = REASONS.get(event.reason, event.reason)
            self.add_line(f"✖ {event.player_id} ({event.seat_label}): {reason}. Gra zakończona.")
        elif isinstance(event, FatalError):
            self.add_line(f"✖ Błąd krytyczny: {event.message}")
