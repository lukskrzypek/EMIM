"""Painted table: card renderers, scene layout, overlays and hot-seat flow (offscreen)."""

from __future__ import annotations

from pathlib import Path

import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFontDatabase, QImage, QPainter, QPixmap
from PySide6.QtWidgets import QPushButton

from controllers.smart_bot import SmartHeartsBot
from engine.contracts import GameContract
from engine.state import GameState
from engine.models import standard_deck
from gui.core.events import DealFinished, MovePlayed, SessionFinished
from gui.core.human_controller import HumanGuiController
from gui.core.seat_config import SeatConfig, SeatKind, SessionConfig
from gui.qt.game_view import GameView
from gui.qt.session_controller import SessionController
from gui.qt.table.card_item import CardItem
from gui.qt.table.pixmap_card_renderer import PixmapCardRenderer
from gui.qt.table.seat_layout import CENTER, SCENE_H, SCENE_W
from gui.qt.table.table_scene import TableScene
from gui.qt.table.vector_card_renderer import VectorCardRenderer, suit_path
from test_core_table_model import Table, _play_full_trick

ALL_CODES = [str(card) for card in standard_deck()]


def _distinct_colors(pixmap: QPixmap) -> int:
    image = pixmap.toImage()
    return len({image.pixel(x, y) for x in range(0, image.width(), 2) for y in range(0, image.height(), 2)})


def _factory(seed: int, deals: int = 1):  # type: ignore[no-untyped-def]
    """A game of 7 deals, started so that ``deals`` of them are still to play."""
    return lambda n: GameState.new(n, seed=seed, start_deal=7 - deals + 1)


def _p0_opens(seed: int):  # type: ignore[no-untyped-def]
    """3 players: P0 declares and opens deal 1, so the table is still empty."""
    return lambda n: GameState.new(n, seed=seed, first_declarer=0, start_deal=1)


# ------------------------------------------------------------------ renderers


def test_vector_renderer_draws_all_52_cards_and_the_back(qapp) -> None:  # type: ignore[no-untyped-def]
    renderer = VectorCardRenderer()
    sizes = set()
    for code in (*ALL_CODES, None):
        pixmap = renderer.pixmap(code, 140)
        assert not pixmap.isNull()
        sizes.add((pixmap.width(), pixmap.height()))
        assert _distinct_colors(pixmap) > 6, code  # not a blank rectangle
    assert sizes == {(140, 200)}


def test_every_card_looks_different(qapp) -> None:  # type: ignore[no-untyped-def]
    renderer = VectorCardRenderer()
    codes = ALL_CODES
    if not QFontDatabase.families():  # the headless Qt platform has no fonts: J/Q/K are text only
        codes = [c for c in codes if c[0] not in "JQK"]
    images = {code: renderer.pixmap(code, 70).toImage() for code in codes}
    assert len({image.constBits().tobytes() for image in images.values()}) == len(codes)


def test_pixmaps_are_cached_and_hidpi_aware(qapp) -> None:  # type: ignore[no-untyped-def]
    renderer = VectorCardRenderer()
    assert renderer.pixmap("QS", 70) is renderer.pixmap("QS", 70)
    sharp = renderer.pixmap("QS", 70, 2.0)
    assert (sharp.width(), sharp.height()) == (140, 200) and sharp.devicePixelRatio() == 2.0


def test_four_color_deck_recolours_clubs_and_diamonds_only(qapp) -> None:  # type: ignore[no-untyped-def]
    renderer = VectorCardRenderer()
    two_color = {c: renderer.pixmap(c, 70).toImage() for c in ("2C", "2D", "2H", "2S")}
    renderer.set_four_color(True)
    four_color = {c: renderer.pixmap(c, 70).toImage() for c in two_color}
    assert four_color["2C"] != two_color["2C"] and four_color["2D"] != two_color["2D"]
    assert four_color["2H"] == two_color["2H"] and four_color["2S"] == two_color["2S"]


def test_suit_paths_are_non_empty_and_centred(qapp) -> None:  # type: ignore[no-untyped-def]
    for suit in "CDSH":
        box = suit_path(suit).boundingRect()
        assert box.width() > 1 and box.height() > 1
        assert abs(box.center().x()) < 0.1
    with pytest.raises(ValueError):
        suit_path("X")


def test_png_renderer_uses_files_and_falls_back_to_vector(qapp, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    red = QPixmap(70, 100)
    red.fill(QColor("#ff0000"))
    assert red.save(str(tmp_path / "2C.png"))
    vector = VectorCardRenderer()
    renderer = PixmapCardRenderer(tmp_path, fallback=vector)

    from_png = renderer.pixmap("2C", 70).toImage()
    assert QColor(from_png.pixel(35, 50)).red() > 240 and QColor(from_png.pixel(35, 50)).green() < 20
    assert renderer.pixmap("AH", 70) is vector.pixmap("AH", 70)  # no AH.png: vector card
    assert renderer.pixmap(None, 70) is vector.pixmap(None, 70)


# --------------------------------------------------------------------- scene


def _scene(table: Table, qtbot=None) -> TableScene:  # type: ignore[no-untyped-def]
    scene = TableScene(table.model, VectorCardRenderer())
    scene.reset_deal(False)
    return scene


def test_scene_places_all_cards_and_shows_only_allowed_hands(qapp) -> None:  # type: ignore[no-untyped-def]
    table = Table(4, humans=("P0",))
    scene = _scene(table)
    assert len(scene.items_by_card) == 52
    viewer_cards = table.model.snapshot.hands["P0"]  # type: ignore[union-attr]
    for code, item in scene.items_by_card.items():
        assert item.face_up == (code in viewer_cards)
        assert 0 <= item.pos().x() <= SCENE_W and 0 <= item.pos().y() <= SCENE_H
    assert all(scene.items_by_card[c].pos().y() > CENTER[1] for c in viewer_cards)  # bottom seat

    table.model.reveal_bots = True
    scene.refresh(False)
    assert all(item.face_up for item in scene.items_by_card.values())


def test_playable_cards_rise_and_the_rest_are_dimmed(qapp) -> None:  # type: ignore[no-untyped-def]
    declarer = GameState.new(4, seed=3).declarer
    pid = f"P{(int(declarer[1:]) + 1) % 4}"  # the player after the declarer must follow suit
    table = Table(4, humans=(pid,), seed=3)
    table.turn()
    table.play_logged()  # the declarer (a bot) opens
    table.turn()
    scene = _scene(table)
    hand = table.model.snapshot.hands[pid]  # type: ignore[union-attr]
    legal = set(table.model.legal_moves)
    assert 0 < len(legal) < len(hand)
    playable = [scene.items_by_card[c] for c in hand if scene.items_by_card[c].legal is True]
    assert {i.code for i in playable} == legal
    others = [scene.items_by_card[c] for c in hand if c not in legal]
    assert all(i.legal is False for i in others)
    assert max(i.pos().y() for i in playable) < min(i.pos().y() for i in others)
    assert all(i.acceptedMouseButtons() == Qt.MouseButton.LeftButton for i in playable)
    assert all(i.acceptedMouseButtons() == Qt.MouseButton.NoButton for i in others)


def test_trick_cards_sit_in_the_middle_then_vanish_into_the_winners_plate(qapp) -> None:  # type: ignore[no-untyped-def]
    table = Table(4, humans=())
    scene = _scene(table)
    _play_full_trick(table)
    scene.refresh(False)
    trick = [scene.items_by_card[c] for c, loc in table.model.card_locations().items() if loc.kind == "trick"]
    assert len(trick) == 4 and all(i.face_up and i.zValue() >= 500 and i.opacity() == 1 for i in trick)
    assert all(abs(i.pos().x() - CENTER[0]) < 220 and abs(i.pos().y() - CENTER[1]) < 140 for i in trick)

    table.turn()
    scene.refresh(False)
    assert all(i.opacity() == 0 for i in trick)


def test_cards_glide_when_animated(qapp, qtbot) -> None:  # type: ignore[no-untyped-def]
    table = Table(4, humans=())
    scene = _scene(table)
    scene.animation_ms = 80
    table.turn()
    table.play_logged()
    card = table.model.snapshot.current_trick[0][1]  # type: ignore[union-attr]
    before = scene.items_by_card[card].pos()
    scene.refresh(True)
    assert scene.items_by_card[card].animating
    qtbot.waitUntil(lambda: not scene.animating, timeout=2000)
    assert scene.items_by_card[card].pos() != before
    scene.refresh(False)
    assert scene.items_by_card[card].zValue() >= 500


def test_plates_follow_the_model(qapp) -> None:  # type: ignore[no-untyped-def]
    table = Table(4, humans=("P1",))
    scene = _scene(table)
    pid = table.turn()
    scene.refresh(False)
    assert scene.plates[pid].is_turn
    assert scene.plates["P1"].is_viewer and not scene.plates["P0"].is_viewer
    assert "lewa 1/13" in scene.info.text()


def test_scene_renders_a_non_empty_picture(qapp) -> None:  # type: ignore[no-untyped-def]
    table = Table(4, humans=())
    scene = _scene(table)
    image = QImage(1100, 740, QImage.Format.Format_ARGB32)
    image.fill(Qt.GlobalColor.black)
    painter = QPainter(image)
    scene.render(painter)
    painter.end()
    assert len({image.pixel(x, y) for x in range(0, 1100, 11) for y in range(0, 740, 11)}) > 20


def test_card_item_clicks_only_when_playable(qapp) -> None:  # type: ignore[no-untyped-def]
    item = CardItem("2C", VectorCardRenderer())
    clicks: list[str] = []
    item.clicked.connect(clicks.append)
    item.set_pose((0, 0), scale=1, z=1, face_up=True, legal=False)
    assert item.acceptedMouseButtons() == Qt.MouseButton.NoButton
    item.set_pose((0, 0), scale=1, z=1, face_up=True, legal=True)
    assert item.acceptedMouseButtons() == Qt.MouseButton.LeftButton


# ------------------------------------------------------------------- overlays


def test_result_overlays_offer_the_right_actions(qapp, qtbot) -> None:  # type: ignore[no-untyped-def]
    session = SessionController(
        SessionConfig((SeatConfig(SeatKind.SMART),) * 3, log_path=None),
        controllers={f"P{i}": SmartHeartsBot(num_samples=0) for i in range(3)},
    )
    view = GameView(session)
    qtbot.addWidget(view)
    view.resize(1200, 800)
    view.show()
    overlay = view.table.result
    labels = {"P0": "A", "P1": "B", "P2": "C"}
    scores = {"P0": 0, "P1": 20, "P2": 240}
    deal = DealFinished(
        1, scores, GameContract.NO_TRICKS, "P0", scores, {"P0": 1, "P1": 0, "P2": 0}, 0
    )

    def buttons() -> list[QPushButton]:
        return overlay.findChildren(QPushButton)

    overlay.show_deal(deal, labels, can_continue=True, waiting=False)
    assert overlay.isVisible()
    assert [b.text() for b in buttons()] == ["Następne rozdanie"]
    with qtbot.waitSignal(overlay.nextDealRequested, timeout=500):
        buttons()[0].click()

    overlay.show_deal(deal, labels, can_continue=False, waiting=True)  # bots carry on alone
    qtbot.waitUntil(lambda: not buttons(), timeout=1000)  # old buttons are deleted later

    done = SessionFinished(scores, {"P0": 1, "P1": 0, "P2": 0}, 0, 1, ("P0",), False)
    overlay.show_session(done, labels)
    qtbot.waitUntil(lambda: [b.text() for b in buttons()] == ["Zagraj ponownie", "Wróć do lobby"], timeout=1000)
    with qtbot.waitSignal(overlay.rematchRequested, timeout=500):
        buttons()[0].click()
    with qtbot.waitSignal(overlay.lobbyRequested, timeout=500):
        buttons()[1].click()
    session.close()


# --------------------------------------------------------------- game screen


def test_hot_seat_flow_through_the_real_ui(qtbot) -> None:  # type: ignore[no-untyped-def]
    config = SessionConfig(
        (SeatConfig(SeatKind.HUMAN), SeatConfig(SeatKind.HUMAN), SeatConfig(SeatKind.SMART, smart_samples=0)),
        log_path=None,
    )
    controllers = {
        "P0": HumanGuiController(),
        "P1": HumanGuiController(),
        "P2": SmartHeartsBot(num_samples=0, seed=2),
    }
    session = SessionController(
        config,
        controllers=controllers,
        engine_factory=lambda n: GameState.new(n, seed=3, first_declarer=0),
    )
    session.pace.delay = 0.0
    view = GameView(session)
    qtbot.addWidget(view)
    view.resize(1200, 800)
    view.show()
    qtbot.waitExposed(view)
    moves: list[MovePlayed] = []
    session.eventsReady.connect(lambda batch: moves.extend(e for e in batch if isinstance(e, MovePlayed)))
    session.start()

    qtbot.waitUntil(view.table.veil.isVisible, timeout=3000)
    first = view.model.veil_for
    assert first in ("P0", "P1")
    assert not any(i.face_up for i in view.table_scene.items_by_card.values())  # nothing leaks
    assert not any(i.legal for i in view.table_scene.items_by_card.values())

    qtbot.mouseClick(view.table.veil.button, Qt.MouseButton.LeftButton)
    assert not view.table.veil.isVisible()
    assert view.model.viewer == first
    own = [c for c, i in view.table_scene.items_by_card.items() if i.face_up]
    assert own and set(own) <= set(view.model.snapshot.hands[first])  # type: ignore[union-attr]

    # A fanned hand overlaps: click the first legal card that is not covered by its neighbour.
    playable, point = next(
        (i, p) for i in view.table_scene.items_by_card.values() if i.legal is True
        for p in [view.table.mapFromScene(i.scenePos())] if view.table.itemAt(p) is i
    )
    qtbot.mouseClick(view.table.viewport(), Qt.MouseButton.LeftButton, pos=point)
    qtbot.waitUntil(lambda: any(m.card == playable.code for m in moves), timeout=3000)
    session.close()


def test_bot_only_table_shows_every_hand_and_locks_the_toggle(qtbot) -> None:  # type: ignore[no-untyped-def]
    session = SessionController(
        SessionConfig((SeatConfig(SeatKind.SMART, smart_samples=0),) * 3, log_path=None),
        controllers={f"P{i}": SmartHeartsBot(num_samples=0, seed=i) for i in range(3)},
        engine_factory=_factory(2),
    )
    session.pace.delay = 0.0
    session.pace.pause()
    view = GameView(session)
    qtbot.addWidget(view)
    session.start()
    qtbot.waitUntil(lambda: len(view.table_scene.items_by_card) == 51, timeout=3000)
    assert all(i.face_up for i in view.table_scene.items_by_card.values())
    assert view.reveal.isChecked() and not view.reveal.isEnabled()
    session.close()


def test_reveal_toggle_flips_bot_cards_with_a_human_at_the_table(qtbot) -> None:  # type: ignore[no-untyped-def]
    config = SessionConfig(
        (SeatConfig(SeatKind.HUMAN), *(SeatConfig(SeatKind.SMART, smart_samples=0),) * 2), log_path=None
    )
    controllers = {
        "P0": HumanGuiController(),
        "P1": SmartHeartsBot(num_samples=0, seed=1),
        "P2": SmartHeartsBot(num_samples=0, seed=2),
    }
    session = SessionController(config, controllers=controllers, engine_factory=_p0_opens(3))
    session.pace.delay = 0.0
    view = GameView(session)
    qtbot.addWidget(view)
    session.start()
    qtbot.waitUntil(lambda: len(view.table_scene.items_by_card) == 51, timeout=3000)
    assert sum(i.face_up for i in view.table_scene.items_by_card.values()) == 17
    view.reveal.setChecked(True)
    assert all(i.face_up for i in view.table_scene.items_by_card.values())
    view.reveal.setChecked(False)
    assert sum(i.face_up for i in view.table_scene.items_by_card.values()) == 17
    session.close()


def test_multi_deal_session_with_a_human_waits_on_the_result_overlay(qtbot) -> None:  # type: ignore[no-untyped-def]
    config = SessionConfig(
        (SeatConfig(SeatKind.HUMAN), *(SeatConfig(SeatKind.SMART, smart_samples=0),) * 2), log_path=None
    )
    human = HumanGuiController()
    session = SessionController(
        config,
        controllers={
            "P0": human,
            "P1": SmartHeartsBot(num_samples=0, seed=1),
            "P2": SmartHeartsBot(num_samples=0, seed=2),
        },
        engine_factory=_p0_opens(3),
    )
    session.pace.delay = 0.0
    view = GameView(session)
    qtbot.addWidget(view)
    view.resize(1200, 800)
    view.show()
    qtbot.waitExposed(view)
    session.start()

    def play_if_needed() -> bool:
        if human.awaiting_move and view.model.interactive_player == "P0":  # UI has seen the turn
            human.submit(sorted(view.model.legal_moves)[0])
        return view.table.result.isVisible()

    qtbot.waitUntil(play_if_needed, timeout=10000)
    assert [b.text() for b in view.table.result.findChildren(QPushButton)] == ["Następne rozdanie"]
    assert view.controls.pause_button.text() == "Wznów"  # the runner paused between deals
    session.pace.resume()
    view.table.result.hide()
    qtbot.waitUntil(lambda: view.model.deal_number == 2, timeout=5000)
    session.close()
