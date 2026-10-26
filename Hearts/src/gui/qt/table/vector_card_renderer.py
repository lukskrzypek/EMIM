"""Playing cards drawn from paths and text: no image assets."""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (
    QBrush,
    QColor,
    QFont,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
    QPolygonF,
)

from gui.qt.table.card_renderer import CachedCardRenderer

INK = QColor("#1b2230")
RED = QColor("#c8323a")
FOUR_COLOR = {"C": QColor("#1f8a4c"), "D": QColor("#2563c9"), "H": RED, "S": INK}
TWO_COLOR = {"C": INK, "D": RED, "H": RED, "S": INK}
PAPER_TOP = QColor("#ffffff")
PAPER_BOTTOM = QColor("#eef0f5")
EDGE = QColor("#aab0bd")
GOLD = QColor("#d9a520")
BACK_BASE = QColor("#27427f")
BACK_LINE = QColor("#3d62b0")

_CENTER_X, _CENTER_Y = 35.0, 50.0
_COL = 13.0
_ROW = 26.0 / 3  # one grid row; pips use rows -3 .. 3

# (column, row) with column in {-1, 0, 1}; rows below the middle are drawn upside down
PIP_LAYOUTS: dict[str, tuple[tuple[float, float], ...]] = {
    "2": ((0, -3), (0, 3)),
    "3": ((0, -3), (0, 0), (0, 3)),
    "4": ((-1, -3), (1, -3), (-1, 3), (1, 3)),
    "5": ((-1, -3), (1, -3), (0, 0), (-1, 3), (1, 3)),
    "6": ((-1, -3), (1, -3), (-1, 0), (1, 0), (-1, 3), (1, 3)),
    "7": ((-1, -3), (1, -3), (0, -1.5), (-1, 0), (1, 0), (-1, 3), (1, 3)),
    "8": ((-1, -3), (1, -3), (0, -1.5), (-1, 0), (1, 0), (0, 1.5), (-1, 3), (1, 3)),
    "9": ((-1, -3), (1, -3), (-1, -1), (1, -1), (0, 0), (-1, 1), (1, 1), (-1, 3), (1, 3)),
    "T": ((-1, -3), (1, -3), (0, -2), (-1, -1), (1, -1), (-1, 1), (1, 1), (0, 2), (-1, 3), (1, 3)),
}


def suit_path(suit: str) -> QPainterPath:
    """Suit symbol as a path inside roughly [-1, 1] x [-1, 1], y pointing down."""
    path = QPainterPath()
    if suit == "H":
        path.moveTo(0, 0.95)
        path.cubicTo(-1.35, 0.1, -0.95, -0.95, 0, -0.38)
        path.cubicTo(0.95, -0.95, 1.35, 0.1, 0, 0.95)
    elif suit == "D":
        path.addPolygon(QPolygonF([QPointF(0, -1), QPointF(0.72, 0), QPointF(0, 1), QPointF(-0.72, 0)]))
        path.closeSubpath()
    elif suit == "S":
        path.moveTo(0, -1.0)
        path.cubicTo(-1.4, -0.05, -0.95, 0.85, 0, 0.35)
        path.cubicTo(0.95, 0.85, 1.4, -0.05, 0, -1.0)
        stem = QPainterPath()
        stem.addPolygon(QPolygonF([QPointF(0, 0.2), QPointF(-0.38, 1.0), QPointF(0.38, 1.0)]))
        stem.closeSubpath()
        path = path.united(stem)
    elif suit == "C":
        for cx, cy in ((0, -0.5), (-0.52, 0.22), (0.52, 0.22)):
            path.addEllipse(QPointF(cx, cy), 0.46, 0.46)
        stem = QPainterPath()
        stem.addPolygon(QPolygonF([QPointF(0, 0.05), QPointF(-0.32, 1.0), QPointF(0.32, 1.0)]))
        stem.closeSubpath()
        path = path.united(stem)
    else:
        raise ValueError(f"Unknown suit {suit!r}")
    return path


class VectorCardRenderer(CachedCardRenderer):
    """Classic playing cards. ``four_color`` separates clubs (green) and diamonds (blue)."""

    def __init__(self, *, four_color: bool = False, font_family: str = "Segoe UI") -> None:
        super().__init__()
        self.four_color = four_color
        self.font_family = font_family
        self._paths = {s: suit_path(s) for s in "CDSH"}

    def set_four_color(self, enabled: bool) -> None:
        if enabled != self.four_color:
            self.four_color = enabled
            self.clear_cache()

    def suit_color(self, suit: str) -> QColor:
        return (FOUR_COLOR if self.four_color else TWO_COLOR)[suit]

    # ------------------------------------------------------------- drawing

    def _draw(self, painter: QPainter, code: str | None, rect: QRectF) -> None:
        if code is None:
            self._draw_back(painter, rect)
        else:
            self._draw_face(painter, code[0], code[1])

    def _card_outline(self) -> QRectF:
        return QRectF(0.75, 0.75, 68.5, 98.5)

    def _draw_back(self, painter: QPainter, rect: QRectF) -> None:
        outline = self._card_outline()
        painter.setPen(QPen(EDGE, 1))
        painter.setBrush(QBrush(QColor("#ffffff")))
        painter.drawRoundedRect(outline, 7, 7)
        inner = outline.adjusted(4, 4, -4, -4)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(BACK_BASE))
        painter.drawRoundedRect(inner, 4, 4)
        painter.save()
        clip = QPainterPath()
        clip.addRoundedRect(inner, 4, 4)
        painter.setClipPath(clip)
        painter.setPen(QPen(BACK_LINE, 1.1))
        step = 8.0
        for i in range(-14, 22):
            offset = i * step
            painter.drawLine(QPointF(inner.left() + offset, inner.top()),
                             QPointF(inner.left() + offset + 100, inner.top() + 100))
            painter.drawLine(QPointF(inner.left() + offset + 100, inner.top()),
                             QPointF(inner.left() + offset, inner.top() + 100))
        painter.restore()
        painter.setPen(QPen(QColor("#dfe6f5"), 1.2))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRoundedRect(inner, 4, 4)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(QColor("#dfe6f5")))
        self._pip(painter, "D", _CENTER_X, _CENTER_Y, 9.5, flip=False)

    def _draw_face(self, painter: QPainter, rank: str, suit: str) -> None:
        color = self.suit_color(suit)
        outline = self._card_outline()
        is_queen_of_spades = rank == "Q" and suit == "S"
        gradient = QLinearGradient(0, 0, 0, 100)
        gradient.setColorAt(0, PAPER_TOP)
        gradient.setColorAt(1, PAPER_BOTTOM)
        painter.setPen(QPen(GOLD if is_queen_of_spades else EDGE, 2.2 if is_queen_of_spades else 1))
        painter.setBrush(QBrush(gradient))
        painter.drawRoundedRect(outline, 7, 7)

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(color))
        for flipped in (False, True):
            painter.save()
            if flipped:
                painter.translate(70, 100)
                painter.rotate(180)
            self._corner_index(painter, rank, suit, color)
            painter.restore()

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(color))
        if rank == "A":
            self._pip(painter, suit, _CENTER_X, _CENTER_Y, 17.0 if suit == "S" else 15.0, flip=False)
        elif rank in PIP_LAYOUTS:
            for column, row in PIP_LAYOUTS[rank]:
                self._pip(painter, suit, _CENTER_X + column * _COL, _CENTER_Y + row * _ROW,
                          7.4, flip=row > 0)
        else:
            self._court_card(painter, rank, suit, color)

        if is_queen_of_spades:
            self._penalty_badge(painter, "13")

    def _corner_index(self, painter: QPainter, rank: str, suit: str, color: QColor) -> None:
        label = "10" if rank == "T" else rank
        font = QFont(self.font_family)
        font.setBold(True)
        font.setPixelSize(15 if label == "10" else 18)
        painter.setFont(font)
        painter.setPen(QPen(color))
        painter.drawText(QRectF(1.0, 2.0, 20, 19), Qt.AlignmentFlag.AlignCenter, label)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(color))
        self._pip(painter, suit, 11.0, 31.0, 6.3, flip=False)

    def _court_card(self, painter: QPainter, rank: str, suit: str, color: QColor) -> None:
        frame = QRectF(15, 19, 40, 62)
        tint = QColor(color)
        tint.setAlpha(22)
        painter.setPen(QPen(color, 1.3))
        painter.setBrush(QBrush(tint))
        painter.drawRoundedRect(frame, 4, 4)
        font = QFont(self.font_family)
        font.setBold(True)
        font.setPixelSize(32)
        painter.setFont(font)
        painter.setPen(QPen(color))
        painter.drawText(QRectF(15, 33, 40, 34), Qt.AlignmentFlag.AlignCenter, rank)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(color))
        self._pip(painter, suit, _CENTER_X, 28.0, 5.8, flip=False)
        self._pip(painter, suit, _CENTER_X, 72.0, 5.8, flip=True)

    def _penalty_badge(self, painter: QPainter, text: str) -> None:
        painter.setPen(QPen(QColor("#8a6a10"), 0.8))
        painter.setBrush(QBrush(GOLD))
        painter.drawEllipse(QPointF(35, 89.5), 7.2, 7.2)
        font = QFont(self.font_family)
        font.setBold(True)
        font.setPixelSize(9)
        painter.setFont(font)
        painter.setPen(QPen(QColor("#2b2106")))
        painter.drawText(QRectF(27.8, 82.5, 14.4, 14), Qt.AlignmentFlag.AlignCenter, text)

    def _pip(self, painter: QPainter, suit: str, x: float, y: float, size: float, *, flip: bool) -> None:
        painter.save()
        painter.translate(x, y)
        if flip:
            painter.rotate(180)
        painter.scale(size, size)
        painter.drawPath(self._paths[suit])
        painter.restore()
