"""The "Bot" tab: a seat's reasoning, thinking time and (for AI bots) its memory pad."""

from __future__ import annotations

from collections.abc import Callable, Sequence

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPlainTextEdit,
    QVBoxLayout,
    QWidget,
)

from gui.core.bot_insight import InsightEntry, InsightModel, SeatInsight, read_ai_memory
from gui.core.cardtext import pretty_card
from gui.core.events import GameEvent, MovePlayed, SessionStarted, TurnStarted
from gui.qt.quality.widgets import VERDICT_COLORS
from gui.qt.theme import TEXT_MUTED, enable_wrapping

KEY_ROLE = Qt.ItemDataRole.UserRole


class BotInsightPanel(QWidget):
    def __init__(
        self,
        labels: dict[str, str],
        human_ids: Sequence[str],
        *,
        memory_models: dict[str, str] | None = None,
        memory_reader: Callable[[str], str] = read_ai_memory,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.model = InsightModel(labels, human_ids)
        self.memory_models = dict(memory_models or {})  # seat -> AI model id
        self._read_memory = memory_reader

        self.seat_box = QComboBox()
        self.follow = QCheckBox("Śledź ostatniego")
        self.follow.setChecked(True)
        self.status = QLabel("")
        self.status.setObjectName("muted")
        self.status.setWordWrap(True)
        self.entries = QListWidget()
        enable_wrapping(self.entries)
        self.reasoning = QPlainTextEdit()
        self.reasoning.setReadOnly(True)
        self.reasoning.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)
        self.reasoning.setPlaceholderText("Uzasadnienie wybranego ruchu")
        self.memory_label = QLabel("Pamięć (scratchpad) modelu")
        self.memory_label.setObjectName("muted")
        self.memory = QPlainTextEdit()
        self.memory.setReadOnly(True)
        self.memory.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)
        self.empty = QLabel("W tej grze nie ma botów do podglądu.")
        self.empty.setObjectName("muted")

        top = QHBoxLayout()
        top.addWidget(self.seat_box, 1)
        top.addWidget(self.follow)
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(8)
        root.addLayout(top)
        root.addWidget(self.status)
        root.addWidget(self.entries, 3)
        root.addWidget(self.reasoning, 2)
        root.addWidget(self.memory_label)
        root.addWidget(self.memory, 2)
        root.addWidget(self.empty)

        self.seat_box.activated.connect(self._on_seat_chosen)
        self.entries.currentItemChanged.connect(self._on_entry_changed)
        self._rebuild_seats()
        self.refresh()

    # ------------------------------------------------------------------ input

    def apply(self, events: Sequence[GameEvent]) -> None:
        changed = False
        for event in events:
            self.model.apply(event)
            if isinstance(event, SessionStarted):
                self._rebuild_seats()
                changed = True
            elif isinstance(event, (MovePlayed, TurnStarted)):
                changed = True
        if changed:
            self.refresh()

    @property
    def shown(self) -> str | None:
        if self.follow.isChecked() and self.model.last_player is not None:
            return self.model.last_player
        return self.seat_box.currentData()

    # ------------------------------------------------------------------ views

    def _rebuild_seats(self) -> None:
        self.seat_box.clear()
        for pid, seat in self.model.seats.items():
            self.seat_box.addItem(f"{pid} · {seat.label}", pid)

    def _on_seat_chosen(self, _index: int) -> None:
        self.follow.setChecked(False)
        self.refresh()

    def refresh(self) -> None:
        has_bots = bool(self.model.seats)
        for widget in (self.seat_box, self.follow, self.status, self.entries, self.reasoning):
            widget.setVisible(has_bots)
        self.empty.setVisible(not has_bots)
        if not has_bots:
            self.memory_label.hide()
            self.memory.hide()
            return
        pid = self.shown
        if pid is None:
            return
        index = self.seat_box.findData(pid)
        if index >= 0 and self.seat_box.currentIndex() != index:
            self.seat_box.setCurrentIndex(index)
        seat = self.model.seats[pid]
        self._show_status(seat)
        self._show_entries(seat)
        self._show_memory(pid)

    def _show_status(self, seat: SeatInsight) -> None:
        thinking = "  ·  myśli…" if self.model.thinking == seat.player_id else ""
        if not seat.moves:
            self.status.setText(f"{seat.player_id} · {seat.label}: jeszcze nie grał{thinking}")
            return
        self.status.setText(
            f"{seat.player_id} · {seat.model or seat.label}: {seat.moves} ruchów · "
            f"średnio {seat.avg_think:.2f} s · najdłużej {seat.think_max:.2f} s{thinking}"
        )

    def _show_entries(self, seat: SeatInsight) -> None:
        latest_selected = self.entries.currentRow() <= 0
        previous = self.entries.currentItem().data(KEY_ROLE) if self.entries.currentItem() else None
        self.entries.blockSignals(True)
        self.entries.clear()
        for entry in reversed(seat.entries):  # newest on top
            item = QListWidgetItem(self._entry_text(entry))
            item.setData(KEY_ROLE, (entry.deal_number, entry.move_number))
            if entry.verdict:
                item.setForeground(QColor(VERDICT_COLORS.get(entry.verdict, TEXT_MUTED)))
            self.entries.addItem(item)
        row = 0
        if not latest_selected and previous is not None:
            for i in range(self.entries.count()):
                if self.entries.item(i).data(KEY_ROLE) == previous:
                    row = i
                    break
        if self.entries.count():
            self.entries.setCurrentRow(row)
        self.entries.blockSignals(False)
        self._show_reasoning(seat, row)

    @staticmethod
    def _entry_text(entry: InsightEntry) -> str:
        verdict = f" · {entry.verdict} {entry.correctness:.0f}" if entry.verdict else ""
        return (
            f"R{entry.deal_number} #{entry.move_number}  {pretty_card(entry.card)}"
            f"  [{entry.think_seconds:.2f} s]{verdict}"
        )

    def _on_entry_changed(self, *_: object) -> None:
        pid = self.shown
        if pid in self.model.seats:
            self._show_reasoning(self.model.seats[pid], self.entries.currentRow())

    def _show_reasoning(self, seat: SeatInsight, row: int) -> None:
        entries = list(reversed(seat.entries))
        if 0 <= row < len(entries):
            text = entries[row].reasoning.strip()
            self.reasoning.setPlainText(text or "(bot nie podał uzasadnienia)")
        else:
            self.reasoning.clear()

    def _show_memory(self, pid: str) -> None:
        model = self.memory_models.get(pid)
        visible = model is not None
        self.memory_label.setVisible(visible)
        self.memory.setVisible(visible)
        if model is not None:
            self.memory_label.setText(f"Pamięć (scratchpad) modelu {model}")
            self.memory.setPlainText(self._read_memory(model))
