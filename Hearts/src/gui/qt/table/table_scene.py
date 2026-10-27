"""The painted table: felt, seat plates, cards. Reads ``TableModel``, never the engine."""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QFont, QPainter, QPen, QRadialGradient
from PySide6.QtWidgets import (
    QGraphicsItem,
    QGraphicsScene,
    QGraphicsSimpleTextItem,
    QStyleOptionGraphicsItem,
    QWidget,
)

from gui.core.table_model import TableModel
from gui.qt.table.card_item import CardItem
from gui.qt.table.card_renderer import CardRenderer
from gui.qt.table.seat_layout import (
    CENTER,
    RX,
    RY,
    SCENE_H,
    SCENE_W,
    TRICK_SCALE,
    fan_positions,
    hand_spec,
    slot_of,
    trick_card_point,
)
from utils.contract_text import WARN_POINTS, contract_label, session_heading
from gui.qt.theme import ACCENT, BORDER, GOOD, SURFACE, TEXT, TEXT_MUTED, WARN

PLATE_W, PLATE_H = 206.0, 50.0
LIFT = 18.0  # playable cards rise above the rest of the hand
DEAL_Z, HAND_Z, TRICK_Z = 0.0, 10.0, 500.0


class SeatPlate(QGraphicsItem):
    """Name, controller and points of one seat; glows while it is that seat's turn."""

    def __init__(self, player_id: str) -> None:
        super().__init__()
        self.player_id = player_id
        self.label = ""
        self.points = 0
        self.is_turn = False
        self.is_viewer = False
        self.status = ""
        self.setZValue(900)

    def boundingRect(self) -> QRectF:
        return QRectF(-PLATE_W / 2 - 6, -PLATE_H / 2 - 6, PLATE_W + 12, PLATE_H + 12)

    def set_state(self, *, label: str, points: int, is_turn: bool, is_viewer: bool, status: str) -> None:
        state = (label, points, is_turn, is_viewer, status)
        if state != (self.label, self.points, self.is_turn, self.is_viewer, self.status):
            self.label, self.points, self.is_turn, self.is_viewer, self.status = state
            self.update()

    def paint(
        self, painter: QPainter, option: QStyleOptionGraphicsItem, widget: QWidget | None = None
    ) -> None:
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(-PLATE_W / 2, -PLATE_H / 2, PLATE_W, PLATE_H)
        if self.is_turn:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(76, 154, 255, 70))
            painter.drawRoundedRect(rect.adjusted(-5, -5, 5, 5), 14, 14)
        painter.setPen(QPen(QColor(ACCENT if self.is_turn else BORDER), 2 if self.is_turn else 1))
        painter.setBrush(QColor(SURFACE))
        painter.drawRoundedRect(rect, 10, 10)

        name_font = QFont("Segoe UI", 10)
        name_font.setBold(True)
        painter.setFont(name_font)
        painter.setPen(QColor(TEXT))
        title = f"{self.player_id}{' (ty)' if self.is_viewer else ''}"
        painter.drawText(
            QRectF(rect.left() + 10, rect.top() + 3, PLATE_W - 70, 22),
            Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
            title,
        )
        big = QFont("Segoe UI", 15)
        big.setBold(True)
        painter.setFont(big)
        painter.setPen(QColor(WARN if self.points >= WARN_POINTS else TEXT))
        painter.drawText(
            QRectF(rect.right() - 62, rect.top() + 1, 52, 26),
            Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight,
            str(self.points),
        )
        small = QFont("Segoe UI", 8)
        painter.setFont(small)
        metrics = painter.fontMetrics()
        status_w = metrics.horizontalAdvance(self.status) + 6 if self.status else 0
        label_w = int(PLATE_W - 20 - status_w)
        painter.setPen(QColor(TEXT_MUTED))
        painter.drawText(
            QRectF(rect.left() + 10, rect.top() + 27, label_w, 18),
            Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
            metrics.elidedText(self.label, Qt.TextElideMode.ElideRight, label_w),
        )
        if self.status:
            painter.setPen(QColor(GOOD if self.is_turn else TEXT_MUTED))
            painter.drawText(
                QRectF(rect.right() - 10 - status_w, rect.top() + 27, status_w, 18),
                Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight,
                self.status,
            )

class TableScene(QGraphicsScene):
    cardClicked = Signal(str)

    def __init__(self, model: TableModel, renderer: CardRenderer, parent: object | None = None) -> None:
        super().__init__(0, 0, SCENE_W, SCENE_H, parent)  # type: ignore[arg-type]
        self.model = model
        self.renderer = renderer
        self.animation_ms = 0
        self.items_by_card: dict[str, CardItem] = {}
        self.plates: dict[str, SeatPlate] = {}
        for pid in model.player_ids:
            plate = SeatPlate(pid)
            self.plates[pid] = plate
            self.addItem(plate)
        self.info = QGraphicsSimpleTextItem()
        self.info.setBrush(QBrush(QColor(TEXT_MUTED)))
        self.info.setFont(QFont("Segoe UI", 11))
        self.info.setPos(22, 14)
        self.info.setZValue(950)
        self.addItem(self.info)

    # -------------------------------------------------------------- background

    def drawBackground(self, painter: QPainter, rect: QRectF) -> None:
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(rect, QColor("#10151c"))
        cx, cy = CENTER
        outer = QRectF(cx - RX - 110, cy - RY - 74, 2 * (RX + 110), 2 * (RY + 100))
        painter.setPen(QPen(QColor("#2a1b10"), 10))
        painter.setBrush(QColor("#3b2616"))
        painter.drawEllipse(outer)
        gradient = QRadialGradient(QPointF(cx, cy), RX + 60)
        gradient.setColorAt(0.0, QColor("#2b7a57"))
        gradient.setColorAt(1.0, QColor("#164a35"))
        painter.setPen(QPen(QColor("#0f3626"), 2))
        painter.setBrush(QBrush(gradient))
        painter.drawEllipse(outer.adjusted(14, 14, -14, -14))

    # ----------------------------------------------------------------- cards

    def reset_deal(self, animate: bool) -> None:
        """Create one item per card of the new deal; with ``animate`` they fly out of the middle."""
        for item in self.items_by_card.values():
            self.removeItem(item)
        self.items_by_card.clear()
        for code in self.model.all_cards:
            item = CardItem(code, self.renderer)
            item.clicked.connect(self.cardClicked)
            item.set_pose(CENTER, scale=0.5, z=DEAL_Z, face_up=False, legal=None)
            self.addItem(item)
            self.items_by_card[code] = item
        self.refresh(animate)

    def refresh(self, animate: bool) -> None:
        model = self.model
        snapshot = model.snapshot
        if snapshot is None:
            return
        ids, n = model.player_ids, len(model.player_ids)
        viewer = model.viewer
        duration = self.animation_ms if animate else 0
        interactive = model.interactive_player
        legal = model.legal_moves

        specs = {pid: hand_spec(slot_of(pid, viewer, ids), n) for pid in ids}
        locations = model.card_locations()

        for pid in ids:
            cards = snapshot.hands[pid]
            spec = specs[pid]
            face_up = model.face_up(pid)
            for index, ((x, y), card) in enumerate(
                zip(fan_positions(len(cards), spec, face_up=face_up), cards, strict=True)
            ):
                item = self.items_by_card.get(card)
                if item is None:
                    continue
                playable: bool | None = None
                if pid == interactive and face_up:
                    playable = card in legal
                    if playable and spec.kind == "row":
                        y -= LIFT
                item.set_pose(
                    (x, y),
                    scale=spec.scale,
                    z=HAND_Z + index,
                    face_up=face_up,
                    legal=playable,
                    duration_ms=duration,
                )

        for card, loc in locations.items():
            item = self.items_by_card.get(card)
            if item is None or loc.kind == "hand":
                continue
            if loc.kind == "trick":
                slot = slot_of(loc.seat, viewer, ids)
                item.set_pose(
                    trick_card_point(slot, n, loc.index),
                    scale=TRICK_SCALE, z=TRICK_Z + loc.index, face_up=True, legal=None,
                    duration_ms=duration,
                )
            else:  # collected: slide into the winner's plate and vanish
                plate = specs[loc.seat].plate
                item.set_pose(
                    plate, scale=0.3, z=DEAL_Z, opacity=0.0, face_up=True, legal=None,
                    duration_ms=duration,
                )
        self.refresh_plates()

    def refresh_plates(self) -> None:
        model = self.model
        snapshot = model.snapshot
        if snapshot is None:
            return
        ids, n = model.player_ids, len(model.player_ids)
        viewer = model.viewer
        for pid, plate in self.plates.items():
            spec = hand_spec(slot_of(pid, viewer, ids), n)
            plate.setPos(*spec.plate)
            is_turn = snapshot.current_player == pid and model.session_result is None
            status = ""
            if is_turn and model.turn_is_human:
                status = "twój ruch"
            elif is_turn and model.thinking_since is not None:
                status = f"myśli… {model.think_elapsed() or 0.0:.1f} s"
            plate.set_state(
                label=model.seat_labels.get(pid, pid),
                points=model.points(pid),
                is_turn=is_turn,
                is_viewer=pid == viewer and model.has_humans,
                status=status,
            )
        total_tricks = snapshot.total_tricks
        self.info.setText(
            f"{session_heading(model.deal_number, model.total_deals)}  ·  "
            f"{contract_label(snapshot.contract)} (rozdaje {snapshot.declarer})  ·  "
            f"lewa {min(snapshot.trick_number, total_tricks)}/{total_tricks}"
        )

    @property
    def animating(self) -> bool:
        return any(item.animating for item in self.items_by_card.values())
