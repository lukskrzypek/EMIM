"""Tempo controls: pause / step / speed / pause after each trick."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QCheckBox, QHBoxLayout, QLabel, QPushButton, QSlider, QWidget

from gui.config import MAX_DELAY_S
from gui.core.pace import PaceControl

_STEPS_PER_SECOND = 10
_SLIDER_MAX = int(MAX_DELAY_S * _STEPS_PER_SECOND)  # rightmost position = no delay (MAX)


def delay_for(position: int) -> float:
    return (_SLIDER_MAX - position) / _STEPS_PER_SECOND


def position_for(delay: float) -> int:
    return max(0, min(_SLIDER_MAX, round(_SLIDER_MAX - delay * _STEPS_PER_SECOND)))


class ControlBar(QWidget):
    """Writes straight into ``PaceControl``; reflects the pause state it is told about."""

    def __init__(self, pace: PaceControl, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._pace = pace

        self.pause_button = QPushButton("Pauza")
        self.pause_button.setMinimumWidth(80)
        self.step_button = QPushButton("Krok")
        self.step_button.setToolTip("Wykonaj jeden ruch (działa w pauzie)")
        self.speed = QSlider(Qt.Orientation.Horizontal)
        self.speed.setRange(0, _SLIDER_MAX)
        self.speed.setFixedWidth(160)
        self.speed.setValue(position_for(pace.delay))
        self.speed_label = QLabel()
        self.speed_label.setMinimumWidth(70)
        self.after_trick = QCheckBox("Pauza po lewie")
        self.after_trick.setChecked(pace.pause_after_trick)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.pause_button)
        layout.addWidget(self.step_button)
        layout.addSpacing(12)
        layout.addWidget(QLabel("Tempo"))
        layout.addWidget(self.speed)
        layout.addWidget(self.speed_label)
        layout.addSpacing(12)
        layout.addWidget(self.after_trick)
        layout.addStretch(1)

        self.pause_button.clicked.connect(self._toggle)
        self.step_button.clicked.connect(pace.step)
        self.speed.valueChanged.connect(self._on_speed)
        self.after_trick.toggled.connect(self._on_after_trick)
        self.set_paused(pace.paused)
        self._on_speed(self.speed.value())

    def set_paused(self, paused: bool) -> None:
        self.pause_button.setText("Wznów" if paused else "Pauza")
        self.step_button.setEnabled(paused)

    def set_enabled_for_session(self, running: bool) -> None:
        for widget in (self.pause_button, self.step_button, self.speed, self.after_trick):
            widget.setEnabled(running)
        if running:
            self.set_paused(self._pace.paused)

    def _toggle(self) -> None:
        self._pace.toggle()

    def _on_speed(self, position: int) -> None:
        delay = delay_for(position)
        self._pace.delay = delay
        self.speed_label.setText("MAX" if delay == 0 else f"{delay:.1f} s / ruch")

    def _on_after_trick(self, checked: bool) -> None:
        self._pace.pause_after_trick = checked
