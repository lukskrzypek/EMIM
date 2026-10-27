"""Panels drawn over the table: hot-seat veil and deal / session results."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from utils.contract_text import contract_label
from gui.core.events import DealFinished, SessionFinished


class VeilOverlay(QFrame):
    """Hides the table until the next hot-seat player confirms they are looking."""

    acknowledged = Signal()

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.setObjectName("veil")
        self.setStyleSheet("QFrame#veil { background: rgba(14, 18, 25, 245); }")
        self.title = QLabel()
        self.title.setObjectName("title")
        self.title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        hint = QLabel("Przekaż komputer tej osobie. Karty zostaną odkryte po kliknięciu.")
        hint.setObjectName("subtitle")
        hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.button = QPushButton("Pokaż moje karty")
        self.button.setObjectName("primary")
        self.button.setMinimumSize(220, 44)
        self.button.clicked.connect(self.acknowledged)
        layout = QVBoxLayout(self)
        layout.addStretch(1)
        layout.addWidget(self.title)
        layout.addWidget(hint)
        layout.addSpacing(16)
        layout.addWidget(self.button, alignment=Qt.AlignmentFlag.AlignCenter)
        layout.addStretch(1)
        self.hide()

    def show_for(self, player_id: str) -> None:
        self.title.setText(f"Tura gracza {player_id}")
        self.setGeometry(self.parentWidget().rect())
        self.raise_()
        self.show()
        self.button.setFocus()


class ResultOverlay(QFrame):
    """Scores after a deal, or the final summary of the session."""

    nextDealRequested = Signal()
    lobbyRequested = Signal()
    rematchRequested = Signal()

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.setObjectName("card")
        self.setStyleSheet(
            "QFrame#card { background: rgba(29, 35, 45, 238); border: 1px solid #2f3847; border-radius: 12px; }"
        )
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(26, 22, 26, 22)
        self._layout.setSpacing(10)
        self.hide()

    def _reset(self) -> None:
        while self._layout.count():
            item = self._layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
            elif item.layout() is not None:
                self._clear_layout(item.layout())

    def _clear_layout(self, layout) -> None:  # type: ignore[no-untyped-def]
        while layout.count():
            item = layout.takeAt(0)
            if item.widget() is not None:
                item.widget().deleteLater()

    def _title(self, text: str, size: int = 20) -> QLabel:
        label = QLabel(text)
        label.setStyleSheet(f"font-size: {size}px; font-weight: 600; background: transparent;")
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        return label

    def _grid(self, header: tuple[str, ...], rows: list[tuple[str, ...]], highlight: set[str]) -> QGridLayout:
        grid = QGridLayout()
        grid.setHorizontalSpacing(22)
        for col, text in enumerate(header):
            label = QLabel(text)
            label.setObjectName("muted")
            label.setAlignment(Qt.AlignmentFlag.AlignCenter if col else Qt.AlignmentFlag.AlignLeft)
            grid.addWidget(label, 0, col)
        for row, cells in enumerate(rows, start=1):
            for col, text in enumerate(cells):
                label = QLabel(text)
                label.setAlignment(Qt.AlignmentFlag.AlignCenter if col else Qt.AlignmentFlag.AlignLeft)
                if cells[0] in highlight:
                    label.setStyleSheet("color: #3ecf8e; font-weight: 600; background: transparent;")
                grid.addWidget(label, row, col)
        return grid

    def show_deal(
        self, result: DealFinished, labels: dict[str, str], *, can_continue: bool, waiting: bool
    ) -> None:
        """``can_continue``: more deals follow and a human presses the button; ``waiting``: bots continue alone."""
        self._reset()
        self._layout.addWidget(self._title(f"Koniec rozdania {result.deal_number}"))
        subtitle = QLabel(f"{contract_label(result.contract)} · rozdawał {result.declarer}")
        subtitle.setObjectName("muted")
        subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._layout.addWidget(subtitle)
        best = min(result.scores.values())
        rows = [
            (f"{pid} · {labels.get(pid, '')}", str(result.scores[pid]), str(result.totals[pid]), str(result.wins[pid]))
            for pid in result.scores
        ]
        winners = {f"{pid} · {labels.get(pid, '')}" for pid, pts in result.scores.items() if pts == best}
        self._layout.addLayout(self._grid(("Gracz", "Kary", "Suma", "Wygrane"), rows, winners))
        if can_continue:
            button = QPushButton("Następne rozdanie")
            button.setObjectName("primary")
            button.setMinimumHeight(40)
            button.clicked.connect(self.nextDealRequested)
            self._layout.addWidget(button)
        elif waiting:
            note = QLabel("Następne rozdanie zaraz się zacznie…")
            note.setObjectName("muted")
            note.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self._layout.addWidget(note)
        self._place()

    def show_session(self, result: SessionFinished, labels: dict[str, str]) -> None:
        self._reset()
        title = "Gra przerwana" if result.aborted else "Koniec gry"
        self._layout.addWidget(self._title(title, 22))
        if result.deals_played:
            winners = ", ".join(result.winners) or "-"
            sub = QLabel(f"Rozegrane rozdania: {result.deals_played}   ·   zwycięża: {winners}")
            sub.setObjectName("muted")
            sub.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self._layout.addWidget(sub)
            rows = [
                (
                    f"{pid} · {labels.get(pid, '')}",
                    str(result.totals[pid]),
                    f"{result.totals[pid] / result.deals_played:.1f}",
                    str(result.wins[pid]),
                )
                for pid in result.totals
            ]
            highlight = {f"{pid} · {labels.get(pid, '')}" for pid in result.winners}
            self._layout.addLayout(self._grid(("Gracz", "Suma", "Średnia", "Wygrane"), rows, highlight))
        buttons = QHBoxLayout()
        again = QPushButton("Zagraj ponownie")
        again.setObjectName("primary")
        again.setMinimumHeight(40)
        again.clicked.connect(self.rematchRequested)
        lobby = QPushButton("Wróć do lobby")
        lobby.setMinimumHeight(40)
        lobby.clicked.connect(self.lobbyRequested)
        buttons.addWidget(again)
        buttons.addWidget(lobby)
        self._layout.addLayout(buttons)
        self._place()

    def _place(self) -> None:
        parent = self.parentWidget()
        self.adjustSize()
        self.move((parent.width() - self.width()) // 2, (parent.height() - self.height()) // 2)
        self.raise_()
        self.show()

    def reposition(self) -> None:
        if self.isVisible():
            self._place()
