"""One card on the table: a graphics item that knows how to glide to a new pose."""

from __future__ import annotations

from PySide6.QtCore import QEasingCurve, QPointF, QPropertyAnimation, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (
    QGraphicsObject,
    QGraphicsSceneHoverEvent,
    QGraphicsSceneMouseEvent,
    QStyleOptionGraphicsItem,
    QWidget,
)

from gui.qt.table.card_renderer import CardRenderer
from gui.qt.table.seat_layout import CARD_H, CARD_W
from gui.qt.theme import ACCENT, ACCENT_HOVER

_CORNER = 7.0


class CardItem(QGraphicsObject):
    """Origin is the card centre, so ``setPos`` / ``setScale`` / ``setRotation`` behave naturally.

    ``legal`` is ``None`` when the card is not part of an interactive hand,
    ``True`` for a playable card and ``False`` for a card that must be dimmed.
    """

    clicked = Signal(str)

    def __init__(self, code: str, renderer: CardRenderer) -> None:
        super().__init__()
        self.code = code
        self.renderer = renderer
        self.face_up = False
        self.legal: bool | None = None
        self._hover = False
        self._animations: list[QPropertyAnimation] = []
        self.setAcceptHoverEvents(True)
        self.setCacheMode(QGraphicsObject.CacheMode.NoCache)

    # --------------------------------------------------------------- geometry

    def boundingRect(self) -> QRectF:
        return QRectF(-CARD_W / 2 - 4, -CARD_H / 2 - 4, CARD_W + 8, CARD_H + 8)

    def shape(self) -> QPainterPath:
        path = QPainterPath()
        path.addRoundedRect(QRectF(-CARD_W / 2, -CARD_H / 2, CARD_W, CARD_H), _CORNER, _CORNER)
        return path

    # ----------------------------------------------------------------- paint

    def paint(
        self, painter: QPainter, option: QStyleOptionGraphicsItem, widget: QWidget | None = None
    ) -> None:
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        device_scale = painter.worldTransform().m11()
        dpr = painter.device().devicePixelRatioF() if painter.device() is not None else 1.0
        pixels = max(16, int(round(CARD_W * abs(device_scale) / 4)) * 4)
        pixmap = self.renderer.pixmap(self.code if self.face_up else None, pixels, 1.0 if dpr <= 0 else dpr)
        rect = QRectF(-CARD_W / 2, -CARD_H / 2, CARD_W, CARD_H)
        painter.drawPixmap(rect, pixmap, QRectF(pixmap.rect()))

        if self.legal is True:
            painter.setPen(QPen(QColor(ACCENT_HOVER if self._hover else ACCENT), 3.2))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRoundedRect(rect.adjusted(-1.5, -1.5, 1.5, 1.5), _CORNER + 1, _CORNER + 1)
        elif self.legal is False:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(10, 14, 22, 130))
            painter.drawRoundedRect(rect, _CORNER, _CORNER)

    # ------------------------------------------------------------ interaction

    def hoverEnterEvent(self, event: QGraphicsSceneHoverEvent) -> None:
        self._hover = True
        if self.legal is True:
            self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.update()

    def hoverLeaveEvent(self, event: QGraphicsSceneHoverEvent) -> None:
        self._hover = False
        self.unsetCursor()
        self.update()

    def mousePressEvent(self, event: QGraphicsSceneMouseEvent) -> None:
        if self.legal is True and event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self.code)
            event.accept()
        else:
            event.ignore()

    # --------------------------------------------------------------- movement

    def set_pose(
        self,
        pos: tuple[float, float],
        *,
        scale: float,
        z: float,
        opacity: float = 1.0,
        face_up: bool,
        legal: bool | None,
        duration_ms: int = 0,
    ) -> None:
        """Move to a pose, gliding when ``duration_ms`` > 0. Face and z change at once."""
        changed_look = self.face_up != face_up or self.legal != legal
        self.face_up, self.legal = face_up, legal
        self.setZValue(z)
        self.setAcceptedMouseButtons(
            Qt.MouseButton.LeftButton if legal is True else Qt.MouseButton.NoButton
        )
        target_pos = QPointF(*pos)
        self._stop_animations()
        if duration_ms <= 0:
            self.setPos(target_pos)
            self.setScale(scale)
            self.setOpacity(opacity)
        else:
            self._animate(b"pos", self.pos(), target_pos, duration_ms)
            self._animate(b"scale", self.scale(), scale, duration_ms)
            self._animate(b"opacity", self.opacity(), opacity, duration_ms)
        if changed_look:
            self.update()

    def _animate(self, prop: bytes, start: object, end: object, duration_ms: int) -> None:
        if start == end:
            return
        animation = QPropertyAnimation(self, prop, self)
        animation.setDuration(duration_ms)
        animation.setStartValue(start)
        animation.setEndValue(end)
        animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        animation.finished.connect(lambda a=animation: self._animations.remove(a) if a in self._animations else None)
        self._animations.append(animation)
        animation.start()

    def _stop_animations(self) -> None:
        for animation in self._animations:
            animation.stop()
        self._animations.clear()

    @property
    def animating(self) -> bool:
        return bool(self._animations)
