"""Statistics card with the memory pad (scratchpad) of every Groq bot playing in this game."""

from __future__ import annotations

from collections.abc import Callable, Mapping

from PySide6.QtWidgets import QFrame, QLabel, QPlainTextEdit, QVBoxLayout, QWidget

from gui.core.bot_insight import read_groq_memory

PAD_HEIGHT = 96


class MemoryBoard(QFrame):
    """One header and one read-only text per Groq seat; hidden when nobody has a memory."""

    def __init__(
        self,
        seat_models: Mapping[str, str],
        seat_labels: Mapping[str, str] | None = None,
        *,
        reader: Callable[[str], str] = read_groq_memory,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("card")
        self.seat_models = dict(seat_models)  # seat id -> Groq model id
        self._labels = dict(seat_labels or {})
        self._reader = reader
        self.headers: dict[str, QLabel] = {}
        self.pads: dict[str, QPlainTextEdit] = {}

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 12)
        layout.setSpacing(6)
        title = QLabel("Pamięć botów (scratchpad)")
        title.setObjectName("muted")
        layout.addWidget(title)
        for pid, model in self.seat_models.items():
            header = QLabel()
            header.setObjectName("muted")
            header.setWordWrap(True)
            pad = QPlainTextEdit()
            pad.setReadOnly(True)
            pad.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)
            pad.setFixedHeight(PAD_HEIGHT)
            layout.addWidget(header)
            layout.addWidget(pad)
            self.headers[pid], self.pads[pid] = header, pad
        self.setVisible(bool(self.seat_models))
        self.refresh()

    def refresh(self, only: str | None = None) -> None:
        """Re-read the files (all seats, or just ``only``); an unchanged text is left alone."""
        for pid, model in self.seat_models.items():
            if only is not None and pid != only:
                continue
            text = self._reader(model)
            pad = self.pads[pid]
            if pad.toPlainText() != text:
                bar = pad.verticalScrollBar()
                at_end = bar.value() >= bar.maximum()
                pad.setPlainText(text)
                if at_end:
                    bar.setValue(bar.maximum())
            self.headers[pid].setText(f"{pid} · {self._labels.get(pid, model)}")
