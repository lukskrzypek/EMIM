"""QGraphicsView that scales the table to the window and hosts the overlays."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QPainter, QResizeEvent
from PySide6.QtWidgets import QFrame, QGraphicsView, QWidget

from gui.qt.table.overlays import ResultOverlay, VeilOverlay
from gui.qt.table.table_scene import TableScene


class TableView(QGraphicsView):
    cardClicked = Signal(str)
    veilAcknowledged = Signal()

    def __init__(self, scene: TableScene, parent: QWidget | None = None) -> None:
        super().__init__(scene, parent)
        self.table_scene = scene
        self.setRenderHints(
            QPainter.RenderHint.Antialiasing
            | QPainter.RenderHint.SmoothPixmapTransform
            | QPainter.RenderHint.TextAntialiasing
        )
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setViewportUpdateMode(QGraphicsView.ViewportUpdateMode.FullViewportUpdate)
        self.setMinimumSize(560, 400)
        scene.cardClicked.connect(self.cardClicked)

        self.veil = VeilOverlay(self)
        self.veil.acknowledged.connect(self.veilAcknowledged)
        self.result = ResultOverlay(self)

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        self.fitInView(self.table_scene.sceneRect(), Qt.AspectRatioMode.KeepAspectRatio)
        if self.veil.isVisible():
            self.veil.setGeometry(self.rect())
        self.result.reposition()
