"""Cards from PNG files, ready to replace the vector look later.

Expected layout of ``directory``: one file per card named by its code
(``2C.png`` ... ``AH.png``, ``TD.png``, ``QS.png``) plus ``back.png``.
Missing files fall back to ``fallback`` (e.g. the vector renderer).
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QRectF
from PySide6.QtGui import QPainter, QPixmap

from gui.qt.table.card_renderer import CachedCardRenderer, CardRenderer


class PixmapCardRenderer(CachedCardRenderer):
    def __init__(self, directory: str | Path, fallback: CardRenderer | None = None) -> None:
        super().__init__()
        self.directory = Path(directory)
        self.fallback = fallback
        self._sources: dict[str | None, QPixmap | None] = {}

    def _source(self, code: str | None) -> QPixmap | None:
        if code not in self._sources:
            path = self.directory / ("back.png" if code is None else f"{code}.png")
            pixmap = QPixmap(str(path)) if path.is_file() else QPixmap()
            self._sources[code] = None if pixmap.isNull() else pixmap
        return self._sources[code]

    def pixmap(self, code: str | None, width_px: int, dpr: float = 1.0) -> QPixmap:
        if self._source(code) is None and self.fallback is not None:
            return self.fallback.pixmap(code, width_px, dpr)
        return super().pixmap(code, width_px, dpr)

    def _draw(self, painter: QPainter, code: str | None, rect: QRectF) -> None:
        source = self._source(code)
        if source is not None:
            painter.drawPixmap(rect, source, QRectF(source.rect()))
