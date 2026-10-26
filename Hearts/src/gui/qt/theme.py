"""Colours, fonts and the application stylesheet (dark theme)."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont, QPalette
from PySide6.QtWidgets import QAbstractItemView, QApplication, QListView, QListWidget

BG = "#14181f"
SURFACE = "#1d232d"
SURFACE_ALT = "#252c38"
BORDER = "#2f3847"
TEXT = "#e6e9ef"
TEXT_MUTED = "#8b95a7"
ACCENT = "#4c9aff"
ACCENT_HOVER = "#6aaeff"
GOOD = "#3ecf8e"
WARN = "#f5b942"
BAD = "#ef5b5b"

STYLESHEET = f"""
QWidget {{ background: {BG}; color: {TEXT}; font-size: 13px; }}
QLabel {{ background: transparent; }}
QLabel#title {{ font-size: 26px; font-weight: 600; }}
QLabel#subtitle, QLabel#muted {{ color: {TEXT_MUTED}; }}
QLabel#warning {{ color: {WARN}; }}
QFrame#card, QWidget#card {{ background: {SURFACE}; border: 1px solid {BORDER}; border-radius: 10px; }}
QFrame#card QLabel, QWidget#card QLabel {{ background: transparent; border: none; }}
QPushButton {{
    background: {SURFACE_ALT}; border: 1px solid {BORDER}; border-radius: 6px; padding: 6px 14px;
}}
QPushButton:hover {{ border-color: {ACCENT}; }}
QPushButton:disabled {{ color: {TEXT_MUTED}; background: {SURFACE}; }}
QPushButton#primary {{ background: {ACCENT}; border-color: {ACCENT}; color: #07121f; font-weight: 600; }}
QPushButton#primary:hover {{ background: {ACCENT_HOVER}; }}
QPushButton#primary:disabled {{ background: {SURFACE_ALT}; color: {TEXT_MUTED}; border-color: {BORDER}; }}
QPushButton#danger:hover {{ border-color: {BAD}; }}
QPushButton#cardButton {{ min-width: 38px; padding: 8px 6px; font-weight: 600; }}
QPushButton#cardButton:enabled {{ border-color: {ACCENT}; }}
QComboBox, QSpinBox, QLineEdit {{
    background: {SURFACE_ALT}; border: 1px solid {BORDER}; border-radius: 6px; padding: 4px 8px;
}}
QComboBox QAbstractItemView {{ background: {SURFACE_ALT}; selection-background-color: {ACCENT}; }}
QListWidget, QTableWidget {{
    background: {SURFACE}; border: 1px solid {BORDER}; border-radius: 8px; gridline-color: {BORDER};
}}
QHeaderView::section {{ background: {SURFACE_ALT}; border: none; padding: 4px 8px; color: {TEXT_MUTED}; }}
QSlider::groove:horizontal {{ height: 4px; background: {BORDER}; border-radius: 2px; }}
QSlider::handle:horizontal {{
    background: {ACCENT}; width: 16px; margin: -6px 0; border-radius: 8px;
}}
QCheckBox {{ background: transparent; }}
QCheckBox::indicator {{ width: 16px; height: 16px; }}
QToolTip {{ background: {SURFACE_ALT}; color: {TEXT}; border: 1px solid {BORDER}; }}
"""


def enable_wrapping(view: QListWidget) -> None:
    """Long items wrap at the view's width: no horizontal scrollbar, no cut-off text."""
    view.setWordWrap(True)
    view.setTextElideMode(Qt.TextElideMode.ElideNone)
    view.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    view.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
    view.setResizeMode(QListView.ResizeMode.Adjust)  # re-wrap when the panel is resized


def apply_theme(app: QApplication) -> None:
    app.setStyle("Fusion")
    palette = QPalette()
    palette.setColor(QPalette.ColorRole.Window, QColor(BG))
    palette.setColor(QPalette.ColorRole.WindowText, QColor(TEXT))
    palette.setColor(QPalette.ColorRole.Base, QColor(SURFACE))
    palette.setColor(QPalette.ColorRole.AlternateBase, QColor(SURFACE_ALT))
    palette.setColor(QPalette.ColorRole.Text, QColor(TEXT))
    palette.setColor(QPalette.ColorRole.Button, QColor(SURFACE_ALT))
    palette.setColor(QPalette.ColorRole.ButtonText, QColor(TEXT))
    palette.setColor(QPalette.ColorRole.Highlight, QColor(ACCENT))
    palette.setColor(QPalette.ColorRole.HighlightedText, QColor("#07121f"))
    app.setPalette(palette)
    app.setFont(QFont("Segoe UI", 10))
    app.setStyleSheet(STYLESHEET)
