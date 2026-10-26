"""TableModel: who sees which hand, hot-seat veil, table rotation, trick collection."""

from __future__ import annotations

from engine.game import HeartsGameEngine
from gui.core.events import (
    DealFinished,
    DealStarted,
    MovePlayed,
    SessionFinished,
    SessionStarted,
    TrickCompleted,
    TurnStarted,
)
from gui.core.snapshot import snapshot_from_engine
from gui.core.table_model import TableModel
from gui.qt.table.seat_layout import (
    CARD_H,
    CARD_W,
    SCENE_H,
    SCENE_W,
    fan_positions,
    hand_spec,
    seat_point,
    slot_of,
    trick_slot_point,
)


class Table:
    """Drives a real engine and feeds the resulting events to a model."""

    def __init__(self, n: int, humans: tuple[str, ...], seed: int = 1) -> None:
        self.engine = HeartsGameEngine(n, seed=seed)
        self.humans = humans
        self.model = TableModel(self.engine.player_ids, humans)
        self.model.apply(
            SessionStarted(self.engine.player_ids, {p: p for p in self.engine.player_ids}, 1)
        )
        self.model.apply(DealStarted(1, 1, self._snap()))
        self.move_no = 0

    def _snap(self):  # type: ignore[no-untyped-def]
        return snapshot_from_engine(self.engine, 1)

    def turn(self) -> str:
        pid = self.engine.current_player
        assert pid is not None
        self.model.apply(TurnStarted(pid, pid in self.humans, self._snap()))
        return pid

    def play_logged(self) -> None:
        """The current player plays their first legal card; emits MovePlayed (+ TrickCompleted)."""
        pid = self.engine.current_player
        assert pid is not None
        before = tuple(self._snap().current_trick)
        card = self.engine.get_legal_moves(pid)[0]
        result = self.engine.play_card(pid, card)
        self.move_no += 1
        self.model.apply(MovePlayed(1, self.move_no, pid, card, "m", 0.0, "", result, self._snap()))
        if result.trick_completed:
            assert result.trick_winner is not None
            self.model.apply(
                TrickCompleted(
                    1, 1, (*before, (pid, card)), result.trick_winner, result.trick_points, self._snap()
                )
            )

def _play_full_trick(t: Table) -> None:
    for _ in range(t.engine.num_players):
        t.turn()
        t.play_logged()


# ---------------------------------------------------------------- visibility


def test_only_bots_means_everything_is_face_up() -> None:
    t = Table(4, humans=())
    assert all(t.model.face_up(p) for p in t.engine.player_ids)
    assert t.model.viewer == "P0"


def test_single_human_sees_own_hand_and_bots_only_on_request() -> None:
    t = Table(4, humans=("P2",))
    assert t.model.viewer == "P2"
    assert t.model.face_up("P2")
    assert not any(t.model.face_up(p) for p in ("P0", "P1", "P3"))
    t.model.reveal_bots = True
    assert all(t.model.face_up(p) for p in t.engine.player_ids)


def test_hot_seat_veil_hides_everything_until_acknowledged() -> None:
    t = Table(3, humans=("P0", "P1"))
    first = t.turn()
    assert first in ("P0", "P1")
    assert t.model.veil_for == first
    assert not any(t.model.face_up(p) for p in t.engine.player_ids)
    assert t.model.interactive_player is None and not t.model.legal_moves

    t.model.acknowledge_veil()
    assert t.model.veil_for is None
    assert t.model.face_up(first)
    assert t.model.viewer == first
    assert t.model.interactive_player == first and t.model.legal_moves


def test_hot_seat_hides_the_hand_after_the_move_and_asks_the_next_human() -> None:
    t = Table(3, humans=("P0", "P1"))
    first = t.turn()
    t.model.acknowledge_veil()
    t.play_logged()
    assert not t.model.face_up(first)  # turn passed on
    second = t.turn()
    if second in ("P0", "P1"):
        assert second != first and t.model.veil_for == second
        t.model.acknowledge_veil()
        assert t.model.viewer == second  # table turns to the new player
        assert not t.model.face_up(first)


def test_same_human_playing_again_needs_no_second_veil() -> None:
    t = Table(2, humans=("P0",))
    t.turn()
    assert t.model.veil_for is None  # a single human never sees a veil


def test_hot_seat_same_player_twice_in_a_row_skips_the_veil() -> None:
    t = Table(3, humans=("P0", "P1"))
    pid = t.turn()
    t.model.acknowledge_veil()
    # Simulate the same player moving again (e.g. after winning a trick).
    t.model.apply(TurnStarted(pid, True, t.model.snapshot))  # type: ignore[arg-type]
    assert t.model.veil_for is None and t.model.viewer == pid


def test_bot_turn_is_not_interactive() -> None:
    t = Table(4, humans=("P1",))
    pid = t.turn()
    assert (pid == "P1") == (t.model.interactive_player == "P1")


# ----------------------------------------------------------------- locations


def test_locations_cover_every_card_at_the_start() -> None:
    t = Table(4, humans=())
    locations = t.model.card_locations()
    assert len(locations) == 52 and {loc.kind for loc in locations.values()} == {"hand"}
    assert sorted(t.model.all_cards) == sorted(locations)
    hand = t.model.snapshot.hands["P1"]  # type: ignore[union-attr]
    assert [locations[c].index for c in hand] == list(range(13))
    assert all(locations[c].count == 13 for c in hand)


def test_played_card_moves_to_the_trick() -> None:
    t = Table(4, humans=())
    t.turn()
    first = t.engine.current_player
    t.play_logged()
    trick = [c for c, loc in t.model.card_locations().items() if loc.kind == "trick"]
    assert trick == ["2C"] and t.model.card_locations()["2C"].seat == first


def test_finished_trick_stays_until_next_turn_then_goes_to_the_winner() -> None:
    t = Table(4, humans=())
    _play_full_trick(t)
    locations = t.model.card_locations()
    assert sum(1 for loc in locations.values() if loc.kind == "trick") == 4
    assert not any(loc.kind == "gone" for loc in locations.values())
    winner = t.model.pending_winner
    assert winner is not None

    t.turn()  # the runner emits TurnStarted only after the hold
    locations = t.model.card_locations()
    gone = {c: loc for c, loc in locations.items() if loc.kind == "gone"}
    assert len(gone) == 4 and {loc.seat for loc in gone.values()} == {winner}
    assert t.model.pending_trick is None


def test_card_between_move_and_trick_events_is_in_limbo_not_in_hand() -> None:
    t = Table(3, humans=())
    for _ in range(2):
        t.turn()
        t.play_logged()
    t.turn()
    pid = t.engine.current_player
    assert pid is not None
    card = t.engine.get_legal_moves(pid)[0]
    result = t.engine.play_card(pid, card)
    t.model.apply(MovePlayed(1, 3, pid, card, "m", 0.0, "", result, snapshot_from_engine(t.engine, 1)))
    assert card not in t.model.card_locations()  # TrickCompleted has not arrived yet


def test_new_deal_and_session_end_reset_state() -> None:
    t = Table(4, humans=("P0",))
    _play_full_trick(t)
    t.turn()
    t.model.apply(DealStarted(2, 2, snapshot_from_engine(HeartsGameEngine(4, seed=9), 2)))
    assert t.model.collected == {} and t.model.pending_trick is None
    assert t.model.deal_number == 2 and len(t.model.all_cards) == 52

    t.model.apply(SessionFinished({}, {}, 0, 0, (), False))
    assert t.model.session_result is not None and t.model.interactive_player is None


def test_deal_finished_clears_turn_and_keeps_result() -> None:
    t = Table(2, humans=())
    event = DealFinished(1, {"P0": 0, "P1": 26}, "P0", {"P0": 0, "P1": 26}, {"P0": 1, "P1": 0}, 0)
    t.model.apply(event)
    assert t.model.deal_result is event and t.model.turn_player is None


# -------------------------------------------------------------------- layout


def test_trick_slots_do_not_overlap_for_any_table_size() -> None:
    for n in (2, 3, 4, 5):
        points = [trick_slot_point(s, n) for s in range(n)]
        for i in range(n):
            for j in range(i + 1, n):
                dx = abs(points[i][0] - points[j][0])
                dy = abs(points[i][1] - points[j][1])
                assert dx >= CARD_W * 0.9 or dy >= CARD_H * 0.9, (n, i, j)


def test_hands_and_plates_stay_inside_the_scene() -> None:
    for n, cards in ((2, 26), (3, 17), (4, 13), (5, 10)):
        for slot in range(n):
            spec = hand_spec(slot, n)
            for face_up in (True, False):
                for x, y in fan_positions(cards, spec, face_up=face_up):
                    half_w, half_h = CARD_W * spec.scale / 2, CARD_H * spec.scale / 2
                    assert half_w <= x <= SCENE_W - half_w and half_h <= y <= SCENE_H - half_h, (n, slot)
            px, py = spec.plate
            assert 103 <= px <= SCENE_W - 103 and 25 <= py <= SCENE_H - 25, (n, slot, spec.plate)


def test_fan_is_centred_and_compresses_to_the_span() -> None:
    spec = hand_spec(2, 4)  # top seat
    xs = [x for x, _ in fan_positions(13, spec, face_up=True)]
    assert abs((xs[0] + xs[-1]) / 2 - spec.cx) < 1e-6
    wide = hand_spec(1, 2)  # 26 cards in one row
    xs = [x for x, _ in fan_positions(26, wide, face_up=True)]
    assert xs[-1] - xs[0] <= wide.max_span - CARD_W * wide.scale + 1e-6
    assert fan_positions(0, spec, face_up=True) == []


def test_slot_rotation_puts_the_viewer_at_the_bottom() -> None:
    ids = ("P0", "P1", "P2", "P3")
    assert slot_of("P2", "P2", ids) == 0
    assert slot_of("P3", "P2", ids) == 1  # next player sits to the viewer's left
    assert seat_point(0, 4)[1] > seat_point(2, 4)[1]
    assert seat_point(1, 4)[0] < seat_point(3, 4)[0]
