"""Application entry point."""

from __future__ import annotations

import sys

from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QApplication

from gui.qt.main_window import MainWindow
from gui.qt.theme import apply_theme


GIL_SWITCH_INTERVAL = 0.0005  # seconds; CPython default is 0.005


def tune_gil() -> None:
    """Let the UI thread get the GIL back quickly while a CPU-bound bot thinks.

    Measured with four ``SmartHeartsBot`` seats: longest UI stall 211 ms -> 12 ms.
    """
    sys.setswitchinterval(GIL_SWITCH_INTERVAL)


def main() -> int:
    tune_gil()
    if QApplication.instance() is None:
        # 125% / 150% Windows scaling: use the real factor instead of rounding to 100% / 200%,
        # so the painted cards stay sharp (the renderer caches pixmaps per device pixel ratio).
        QGuiApplication.setHighDpiScaleFactorRoundingPolicy(
            Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
        )
    app = QApplication.instance() or QApplication(sys.argv)
    apply_theme(app)  # type: ignore[arg-type]
    window = MainWindow()
    window.show()
    return app.exec()
