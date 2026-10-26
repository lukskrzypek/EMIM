"""Small custom-painted charts: gauge, verdict bar, sparkline, horizontal bars.

No chart library: every widget is a few dozen lines of ``QPainter``.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QSizePolicy, QWidget

from gui.qt.theme import ACCENT, BAD, BORDER, GOOD, SURFACE_ALT, TEXT, TEXT_MUTED, WARN

VERDICT_COLORS = {
    "optymalne": GOOD,
    "poprawne": ACCENT,
    "wątpliwe": WARN,
    "niepoprawne": BAD,
}
VERDICT_SHORT = {
    "optymalne": "optym.",
    "poprawne": "popraw.",
    "wątpliwe": "wątpl.",
    "niepoprawne": "niepop.",
}


def correctness_color(value: float) -> str:
    """Same thresholds as ``evaluation.evaluator.verdict_for``."""
    if value >= 90:
        return VERDICT_COLORS["optymalne"]
    if value >= 70:
        return VERDICT_COLORS["poprawne"]
    if value >= 40:
        return VERDICT_COLORS["wątpliwe"]
    return VERDICT_COLORS["niepoprawne"]


def _elide(text: str, font: QFont, width: float) -> str:
    return QFontMetrics(font).elidedText(text, Qt.TextElideMode.ElideRight, max(0, int(width)))


class GaugeWidget(QWidget):
    """Open ring gauge, 0-100. ``None`` shows an empty ring with a dash."""

    def __init__(self, title: str, *, graded: bool = True, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.title = title
        self.graded = graded  # colour by quality thresholds; otherwise a neutral accent
        self.value: float | None = None
        self.caption = ""
        self.setMinimumSize(110, 110)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)

    def set_value(self, value: float | None, caption: str = "") -> None:
        self.value, self.caption = value, caption
        self.update()

    def paintEvent(self, event) -> None:  # type: ignore[no-untyped-def]
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        title_h = 18
        side = min(w, h - title_h) - 14
        box = QRectF((w - side) / 2, title_h + 4, side, side)
        start, span = 225 * 16, -270 * 16  # opens at the bottom
        track = QPen(QColor(BORDER), 9)
        track.setCapStyle(Qt.PenCapStyle.RoundCap)
        p.setPen(track)
        p.drawArc(box, start, span)
        if self.value is not None:
            colour = correctness_color(self.value) if self.graded else ACCENT
            bar = QPen(QColor(colour), 9)
            bar.setCapStyle(Qt.PenCapStyle.RoundCap)
            p.setPen(bar)
            p.drawArc(box, start, int(span * max(0.0, min(100.0, self.value)) / 100))

        title_font = QFont(self.font())
        title_font.setPointSizeF(8.5)
        p.setFont(title_font)
        p.setPen(QColor(TEXT_MUTED))
        p.drawText(QRectF(0, 0, w, title_h), Qt.AlignmentFlag.AlignCenter, self.title)

        value_font = QFont(self.font())
        value_font.setPointSizeF(max(11.0, side / 5))
        value_font.setBold(True)
        p.setFont(value_font)
        p.setPen(QColor(TEXT))
        text = "–" if self.value is None else f"{self.value:.0f}"
        p.drawText(box, Qt.AlignmentFlag.AlignCenter, text)
        if self.caption:
            small = QFont(self.font())
            small.setPointSizeF(8.0)
            p.setFont(small)
            p.setPen(QColor(TEXT_MUTED))
            p.drawText(
                QRectF(box.left(), box.bottom() - 18, box.width(), 18),
                Qt.AlignmentFlag.AlignCenter,
                _elide(self.caption, small, box.width()),
            )


class VerdictBar(QWidget):
    """Stacked bar with the share of each verdict plus a legend."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.shares: dict[str, float] = {}
        self.setMinimumHeight(46)

    def set_shares(self, shares: dict[str, float]) -> None:
        self.shares = dict(shares)
        self.update()

    def paintEvent(self, event) -> None:  # type: ignore[no-untyped-def]
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w = self.width()
        bar = QRectF(0, 2, w, 14)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(BORDER))
        p.drawRoundedRect(bar, 7, 7)
        total = sum(self.shares.values())
        if total > 0:
            p.save()
            path = QPainterPath()
            path.addRoundedRect(bar, 7, 7)
            p.setClipPath(path)
            x = 0.0
            for verdict, colour in VERDICT_COLORS.items():
                share = self.shares.get(verdict, 0.0) / total
                if share <= 0:
                    continue
                p.setBrush(QColor(colour))
                p.drawRect(QRectF(x, bar.top(), share * w + 1, bar.height()))
                x += share * w
            p.restore()

        font = QFont(self.font())
        font.setPointSizeF(8.5)
        p.setFont(font)
        column = w / len(VERDICT_COLORS)
        for i, (verdict, colour) in enumerate(VERDICT_COLORS.items()):
            x = i * column
            p.setBrush(QColor(colour))
            p.setPen(Qt.PenStyle.NoPen)
            p.drawEllipse(QPointF(x + 5, 32), 4, 4)
            share = self.shares.get(verdict, 0.0)
            p.setPen(QColor(TEXT_MUTED))
            p.drawText(
                QRectF(x + 13, 22, column - 13, 20),
                Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                f"{VERDICT_SHORT[verdict]} {100 * share:.0f}%",
            )


@dataclass(frozen=True)
class SparkPoint:
    value: float
    colour: str


class Sparkline(QWidget):
    """Correctness of recent decisions (0-100) with the verdict thresholds as guides."""

    MAX_POINTS = 60

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.points: list[SparkPoint] = []
        self.setMinimumHeight(84)

    def set_points(self, points: Sequence[SparkPoint]) -> None:
        self.points = list(points)[-self.MAX_POINTS :]
        self.update()

    def paintEvent(self, event) -> None:  # type: ignore[no-untyped-def]
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        left, top, bottom = 26.0, 6.0, 6.0
        plot = QRectF(left, top, w - left - 6, h - top - bottom)

        small = QFont(self.font())
        small.setPointSizeF(7.5)
        p.setFont(small)
        for level in (40, 70, 90):
            y = plot.bottom() - plot.height() * level / 100
            p.setPen(QPen(QColor(BORDER), 1, Qt.PenStyle.DashLine))
            p.drawLine(QPointF(plot.left(), y), QPointF(plot.right(), y))
            p.setPen(QColor(TEXT_MUTED))
            p.drawText(QRectF(0, y - 7, left - 4, 14), Qt.AlignmentFlag.AlignRight, str(level))

        if not self.points:
            p.setPen(QColor(TEXT_MUTED))
            p.drawText(plot, Qt.AlignmentFlag.AlignCenter, "brak ocenionych ruchów")
            return

        n = len(self.points)
        step = plot.width() / max(1, n - 1) if n > 1 else 0
        coords = [
            QPointF(
                plot.left() + (i * step if n > 1 else plot.width() / 2),
                plot.bottom() - plot.height() * max(0.0, min(100.0, pt.value)) / 100,
            )
            for i, pt in enumerate(self.points)
        ]
        p.setPen(QPen(QColor(TEXT_MUTED), 1.4))
        for a, b in zip(coords, coords[1:], strict=False):
            p.drawLine(a, b)
        p.setPen(Qt.PenStyle.NoPen)
        for point, pt in zip(coords, self.points, strict=True):
            p.setBrush(QColor(pt.colour))
            p.drawEllipse(point, 3.2, 3.2)


@dataclass(frozen=True)
class BarRow:
    label: str
    value: float  # 0-100
    colour: str
    note: str = ""
    emphasis: bool = False


class BarList(QWidget):
    """Rows ``label | bar | value + note``; one row may be emphasised."""

    ROW_H = 22

    def __init__(self, *, label_width: int = 64, empty_text: str = "", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.rows: list[BarRow] = []
        self.label_width = label_width
        self.empty_text = empty_text
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._resize()

    def set_rows(self, rows: Sequence[BarRow]) -> None:
        self.rows = list(rows)
        self._resize()
        self.update()

    def _resize(self) -> None:
        self.setFixedHeight(max(1, len(self.rows)) * self.ROW_H + 2)

    def paintEvent(self, event) -> None:  # type: ignore[no-untyped-def]
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w = self.width()
        if not self.rows:
            p.setPen(QColor(TEXT_MUTED))
            p.drawText(QRectF(0, 0, w, self.ROW_H), Qt.AlignmentFlag.AlignVCenter, self.empty_text)
            return
        value_w = 96
        bar_left = self.label_width + 6
        bar_w = max(20.0, w - bar_left - value_w)
        for i, row in enumerate(self.rows):
            y = 1 + i * self.ROW_H
            if row.emphasis:
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(QColor(SURFACE_ALT))
                p.drawRoundedRect(QRectF(0, y, w, self.ROW_H - 2), 5, 5)
            font = QFont(self.font())
            font.setBold(row.emphasis)
            p.setFont(font)
            p.setPen(QColor(TEXT))
            p.drawText(
                QRectF(6, y, self.label_width, self.ROW_H - 2),
                Qt.AlignmentFlag.AlignVCenter,
                row.label,
            )
            track = QRectF(bar_left, y + 6, bar_w, 8)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(BORDER))
            p.drawRoundedRect(track, 4, 4)
            p.setBrush(QColor(row.colour))
            fill = QRectF(track.left(), track.top(), track.width() * max(0.0, min(100.0, row.value)) / 100, 8)
            p.drawRoundedRect(fill, 4, 4)
            small = QFont(self.font())
            small.setPointSizeF(8.5)
            p.setFont(small)
            p.setPen(QColor(TEXT_MUTED if not row.emphasis else TEXT))
            p.drawText(
                QRectF(bar_left + bar_w + 6, y, value_w - 8, self.ROW_H - 2),
                Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                _elide(f"{row.value:.0f}  {row.note}".strip(), small, value_w - 8),
            )
