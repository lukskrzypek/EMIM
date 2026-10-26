"""Card drawing contract. Swap the renderer to change the look of every card.

A renderer turns a card code (``QS``, ``TH``; ``None`` = card back) into a pixmap.
``CardItem`` only calls ``pixmap()``, so replacing the vector cards by PNG files
means passing a ``PixmapCardRenderer`` instead of a ``VectorCardRenderer``.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Protocol

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QPainter, QPixmap

from gui.qt.table.seat_layout import CARD_H, CARD_W


class CardRenderer(Protocol):
    def pixmap(self, code: str | None, width_px: int, dpr: float = 1.0) -> QPixmap:
        """Card face (or back for ``None``) with the given logical width in pixels."""
        ...


class CachedCardRenderer(ABC):
    """Draws in a fixed 70x100 coordinate system and caches the pixmaps it produces."""

    def __init__(self) -> None:
        self._cache: dict[tuple[str | None, int, float], QPixmap] = {}

    def pixmap(self, code: str | None, width_px: int, dpr: float = 1.0) -> QPixmap:
        width_px = max(8, int(width_px))
        key = (code, width_px, round(dpr, 2))
        cached = self._cache.get(key)
        if cached is not None:
            return cached
        device_w = max(1, round(width_px * dpr))
        device_h = max(1, round(width_px * CARD_H / CARD_W * dpr))
        pixmap = QPixmap(device_w, device_h)
        pixmap.setDevicePixelRatio(dpr)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHints(
            QPainter.RenderHint.Antialiasing
            | QPainter.RenderHint.TextAntialiasing
            | QPainter.RenderHint.SmoothPixmapTransform
        )
        painter.scale(device_w / CARD_W / dpr, device_h / CARD_H / dpr)
        self._draw(painter, code, QRectF(0, 0, CARD_W, CARD_H))
        painter.end()
        self._cache[key] = pixmap
        return pixmap

    def clear_cache(self) -> None:
        self._cache.clear()

    @abstractmethod
    def _draw(self, painter: QPainter, code: str | None, rect: QRectF) -> None:
        """Paint ``code`` into ``rect`` (always 70x100 logical units)."""
