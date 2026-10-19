"""Tests for the Hearts game engine."""

from __future__ import annotations

import random
from collections.abc import Callable

import pytest

from engine.game import (
    HeartsGameEngine,
    IllegalMoveError,
    PlayerObservation,
    card_points,
)
from engine.models import Card

ALL_RANKS = "23456789TJQKA"


def hand(spec: str) -> list[str]:
    """Parse ``"C2TA D234"`` (suit letter followed by rank letters) into card codes."""
    cards: list[str] = []
    for token in spec.split():
        suit, ranks = token[0], token[1:]
        cards.extend(rank + suit for rank in ranks)
    return sorted(cards, key=Card.parse)


def make_engine(*specs: str) -> HeartsGameEngine:
    return HeartsGameEngine(len(specs), hands=[hand(s) for s in specs])


def play(engine: HeartsGameEngine, moves: str) -> None:
    """Play ``"P0:2C P1:3C"`` in order."""
    for token in moves.split():
        player, card = token.split(":")
        engine.play_card(player, card)


def play_out(
    engine: HeartsGameEngine, choose: Callable[[list[str]], str] = lambda legal: legal[0]
) -> None:
    while not engine.is_over:
        player = engine.current_player
        assert player is not None
        legal = engine.get_legal_moves(player)
        assert legal, f"{player} has no legal moves"
        engine.play_card(player, choose(legal))


# 4 players, mixed hands. P3 wins trick 1 with 9C.
MIX = (
    "C2TA D234 S2345 H234",
    "C345 D5678 S678 H567",
    "C678 D9TJQ S9TJ H89T",
    "C9JQK DKA SQKA HJQKA",
)
# P0 owns all clubs, P1 diamonds, P2 spades, P3 hearts: P0 shoots the moon.
MOON = (
    "C" + ALL_RANKS,
    "D" + ALL_RANKS,
    "S" + ALL_RANKS,
    "H" + ALL_RANKS,
)
# P1 wins trick 1 and is left with hearts only.
HEARTS_ONLY = (
    "C23456789 D2345 HA",
    "CA H23456789TJQK",
    "CTJQK D6789TJQKA",
    "S" + ALL_RANKS,
)
# 5 players: P4 holds only point cards (QS + 9 hearts).
FIVE = (
    "C23456789TJ",
    "CQKA D3456789",
    "DTJQKA S34567",
    "S89TJKA H2345",
    "SQ H6789TJQKA",
)


# ------------------------------------------------------------------ setup


@pytest.mark.parametrize(("players", "hand_size"), [(2, 26), (3, 17), (4, 13), (5, 10)])
def test_deal_sizes(players: int, hand_size: int) -> None:
    engine = HeartsGameEngine(players, seed=1)
    assert engine.player_ids == tuple(f"P{i}" for i in range(players))
    for pid in engine.player_ids:
        assert len(engine.get_player_observation(pid).hand) == hand_size


@pytest.mark.parametrize("players", [2, 3, 4, 5])
def test_deal_is_a_partition_of_the_deck(players: int) -> None:
    engine = HeartsGameEngine(players, seed=2)
    cards = [c for pid in engine.player_ids for c in engine.get_player_observation(pid).hand]
    assert len(cards) == len(set(cards)) == {2: 52, 3: 51, 4: 52, 5: 50}[players]
    assert ("2D" in cards) == (players in (2, 4))
    assert ("2S" in cards) == (players != 5)


@pytest.mark.parametrize("players", [2, 3, 4, 5])
@pytest.mark.parametrize("seed", range(5))
def test_holder_of_2c_starts_and_must_lead_it(players: int, seed: int) -> None:
    engine = HeartsGameEngine(players, seed=seed)
    starter = engine.current_player
    assert starter is not None
    assert "2C" in engine.get_player_observation(starter).hand
    assert engine.get_legal_moves(starter) == ["2C"]
    for pid in engine.player_ids:
        if pid != starter:
            assert engine.get_legal_moves(pid) == []


def test_same_seed_gives_same_deal() -> None:
    a = HeartsGameEngine(4, seed=42).get_player_observation("P0")
    b = HeartsGameEngine(4, seed=42).get_player_observation("P0")
    assert a.hand == b.hand


@pytest.mark.parametrize("players", [0, 1, 6])
def test_unsupported_player_count(players: int) -> None:
    with pytest.raises(ValueError):
        HeartsGameEngine(players)


def test_custom_hands_are_validated() -> None:
    good = [hand(s) for s in MIX]
    with pytest.raises(ValueError):
        HeartsGameEngine(4, hands=good[:3])
    with pytest.raises(ValueError):
        HeartsGameEngine(4, hands=[good[0], good[1], good[2], good[3][:-1] + ["2C"]])
    with pytest.raises(ValueError):
        HeartsGameEngine(4, hands=[good[0][:-1], good[1] + [good[0][-1]], good[2], good[3]])


def test_custom_hands_set_starting_player() -> None:
    engine = make_engine(*MIX)
    assert engine.current_player == "P0"
    engine = make_engine(MIX[1], MIX[0], MIX[2], MIX[3])
    assert engine.current_player == "P1"


def test_card_points() -> None:
    assert card_points(Card.parse("QS")) == 13
    assert card_points(Card.parse("2H")) == 1
    assert card_points(Card.parse("AH")) == 1
    assert card_points(Card.parse("KS")) == 0
    assert card_points(Card.parse("QD")) == 0


# --------------------------------------------------------------- first trick


def test_first_trick_must_follow_clubs() -> None:
    engine = make_engine(*MIX)
    engine.play_card("P0", "2C")
    assert engine.get_legal_moves("P1") == ["3C", "4C", "5C"]


def test_first_trick_void_player_cannot_dump_points() -> None:
    engine = make_engine(*FIVE)
    play(engine, "P0:2C P1:QC")
    # P2: no clubs, no point cards -> anything.
    assert len(engine.get_legal_moves("P2")) == 10
    engine.play_card("P2", "TD")
    # P3: no clubs, holds spades and hearts -> hearts forbidden.
    assert engine.get_legal_moves("P3") == hand("S89TJKA")
    with pytest.raises(IllegalMoveError):
        engine.play_card("P3", "2H")


def test_first_trick_void_player_with_only_points_may_play_anything() -> None:
    engine = make_engine(*FIVE)
    play(engine, "P0:2C P1:QC P2:TD P3:8S")
    legal = engine.get_legal_moves("P4")
    assert legal == hand("SQ H6789TJQKA")
    assert "QS" in legal


def test_first_trick_all_hearts_hand_may_play_any_heart() -> None:
    engine = make_engine(*MOON)
    engine.play_card("P0", "2C")
    engine.play_card("P1", "2D")
    engine.play_card("P2", "2S")
    assert engine.get_legal_moves("P3") == hand("H" + ALL_RANKS)


def test_first_trick_qs_not_allowed_when_other_spades_available() -> None:
    engine = make_engine(*MOON)
    engine.play_card("P0", "2C")
    engine.play_card("P1", "2D")
    legal = engine.get_legal_moves("P2")
    assert "QS" not in legal
    assert len(legal) == 12
    with pytest.raises(IllegalMoveError):
        engine.play_card("P2", "QS")


def test_first_trick_follow_suit_beats_point_restriction() -> None:
    # Having clubs means following clubs, regardless of points elsewhere.
    engine = make_engine(*FIVE)
    engine.play_card("P0", "2C")
    assert engine.get_legal_moves("P1") == ["QC", "KC", "AC"]


# ------------------------------------------------------------ follow suit


def test_must_follow_lead_suit_later_in_the_hand() -> None:
    engine = make_engine(*MIX)
    play(engine, "P0:2C P1:3C P2:6C P3:9C P3:JC")
    assert engine.get_legal_moves("P0") == ["TC", "AC"]
    engine.play_card("P0", "AC")
    assert engine.get_legal_moves("P1") == ["4C", "5C"]
    with pytest.raises(IllegalMoveError):
        engine.play_card("P1", "5D")


# ------------------------------------------------------------ hearts / leads


def test_cannot_lead_hearts_before_they_are_broken() -> None:
    engine = make_engine(*MIX)
    play(engine, "P0:2C P1:3C P2:6C P3:9C")
    assert not engine.hearts_broken
    assert engine.current_player == "P3"
    legal = engine.get_legal_moves("P3")
    assert legal == hand("CJQK DKA SQKA")
    assert all(not c.endswith("H") for c in legal)
    with pytest.raises(IllegalMoveError):
        engine.play_card("P3", "JH")


def _play_until_hearts_broken(engine: HeartsGameEngine) -> None:
    play(engine, "P0:2C P1:3C P2:6C P3:9C")  # T1 -> P3
    play(engine, "P3:JC P0:AC P1:4C P2:7C")  # T2 -> P0
    play(engine, "P0:TC P1:5C P2:8C P3:QC")  # T3 -> P3
    # P3 leads KC; P0, P1, P2 are all out of clubs.


def test_discarding_a_heart_breaks_hearts_and_allows_leading_them() -> None:
    engine = make_engine(*MIX)
    _play_until_hearts_broken(engine)
    assert not engine.hearts_broken
    engine.play_card("P3", "KC")
    assert engine.get_legal_moves("P0") == hand("D234 S2345 H234")  # void: anything
    engine.play_card("P0", "2H")
    assert engine.hearts_broken
    play(engine, "P1:5D P2:8H")
    assert engine.current_player == "P3"
    assert "JH" in engine.get_legal_moves("P3")
    assert len(engine.get_legal_moves("P3")) == 9


def test_discarding_non_heart_does_not_break_hearts() -> None:
    engine = make_engine(*MIX)
    _play_until_hearts_broken(engine)
    play(engine, "P3:KC P0:2D P1:5D P2:9D")
    assert not engine.hearts_broken


def test_queen_of_spades_does_not_break_hearts() -> None:
    engine = make_engine(*FIVE)
    play(engine, "P0:2C P1:QC P2:TD P3:8S P4:QS")
    assert not engine.hearts_broken
    assert engine.current_player == "P1"


def test_heart_dumped_in_first_trick_breaks_hearts() -> None:
    engine = make_engine(*FIVE)
    play(engine, "P0:2C P1:QC P2:TD P3:8S P4:6H")
    assert engine.hearts_broken


def test_hearts_only_hand_may_lead_hearts_unbroken() -> None:
    engine = make_engine(*HEARTS_ONLY)
    play(engine, "P0:2C P1:AC P2:TC P3:2S")
    assert engine.current_player == "P1"
    assert not engine.hearts_broken
    assert engine.get_legal_moves("P1") == hand("H23456789TJQK")


def test_hearts_only_lead_breaks_hearts_and_others_follow() -> None:
    engine = make_engine(*HEARTS_ONLY)
    play(engine, "P0:2C P1:AC P2:TC P3:2S")
    engine.play_card("P1", "2H")
    assert engine.hearts_broken
    assert engine.get_legal_moves("P2") == hand("CJQK D6789TJQKA")  # void in hearts
    engine.play_card("P2", "6D")
    assert engine.get_legal_moves("P3") == hand("S3456789TJQKA")  # void in hearts
    engine.play_card("P3", "3S")
    # P0 holds a single heart (AH) and must follow with it.
    assert engine.get_legal_moves("P0") == ["AH"]


# ------------------------------------------------------- exposed voids


def test_void_detected_when_not_following_suit() -> None:
    engine = make_engine(*FIVE)
    play(engine, "P0:2C P1:QC P2:TD P3:8S P4:6H")
    voids = engine.exposed_voids
    assert voids["P0"] == []
    assert voids["P1"] == []
    assert voids["P2"] == ["C"]
    assert voids["P3"] == ["C"]
    assert voids["P4"] == ["C"]


def test_following_suit_exposes_nothing() -> None:
    engine = make_engine(*MIX)
    play(engine, "P0:2C P1:3C P2:6C P3:9C")
    assert all(v == [] for v in engine.exposed_voids.values())


def test_voids_for_all_players_exposed_when_clubs_run_out() -> None:
    engine = make_engine(*MIX)
    _play_until_hearts_broken(engine)
    play(engine, "P3:KC P0:2H P1:5D P2:8H")
    assert engine.exposed_voids == {"P0": ["C"], "P1": ["C"], "P2": ["C"], "P3": []}


def test_second_void_suit_is_added_in_suit_order() -> None:
    engine = make_engine(*HEARTS_ONLY)
    play(engine, "P0:2C P1:AC P2:TC P3:2S")
    assert engine.exposed_voids["P3"] == ["C"]
    play(engine, "P1:2H P2:6D P3:3S")
    assert engine.exposed_voids["P2"] == ["H"]
    assert engine.exposed_voids["P3"] == ["C", "H"]
    assert engine.exposed_voids["P0"] == []


# ------------------------------------------------------------- trick logic


def test_trick_winner_leads_next_and_history_is_recorded() -> None:
    engine = make_engine(*MIX)
    play(engine, "P0:2C P1:3C P2:6C")
    result = engine.play_card("P3", "9C")
    assert result.trick_completed
    assert result.trick_winner == "P3"
    assert result.trick_points == 0
    assert not result.hand_over
    assert engine.current_player == "P3"
    assert engine.trick_number == 2
    obs = engine.get_player_observation("P3")
    assert obs.trick_history == ["T1: P0:2C, P1:3C, P2:6C, P3:9C -> Win:P3 (0pts)"]
    assert obs.current_trick == []


def test_off_suit_cards_never_win() -> None:
    engine = make_engine(*FIVE)
    result = None
    for move in "P0:2C P1:QC P2:TD P3:8S P4:QS".split():
        player, card = move.split(":")
        result = engine.play_card(player, card)
    assert result is not None
    assert result.trick_winner == "P1"
    assert result.trick_points == 13
    assert engine.points_taken["P1"] == 13
    assert engine.get_player_observation("P0").trick_history == [
        "T1: P0:2C, P1:QC, P2:TD, P3:8S, P4:QS -> Win:P1 (13pts)"
    ]


def test_history_order_starts_from_trick_leader() -> None:
    engine = make_engine(*MIX)
    play(engine, "P0:2C P1:3C P2:6C P3:9C P3:JC P0:AC P1:4C P2:7C")
    history = engine.get_player_observation("P0").trick_history
    assert history[1] == "T2: P3:JC, P0:AC, P1:4C, P2:7C -> Win:P0 (0pts)"
    assert engine.current_player == "P0"


def test_current_trick_in_observation() -> None:
    engine = make_engine(*MIX)
    play(engine, "P0:2C P1:3C")
    obs = engine.get_player_observation("P2")
    assert obs.current_trick == [("P0", "2C"), ("P1", "3C")]
    assert obs.legal_moves == ["6C", "7C", "8C"]


# --------------------------------------------------------------- errors


def test_out_of_turn_move_rejected() -> None:
    engine = make_engine(*MIX)
    with pytest.raises(IllegalMoveError):
        engine.play_card("P1", "3C")


def test_card_not_in_hand_rejected() -> None:
    engine = make_engine(*MIX)
    with pytest.raises(IllegalMoveError):
        engine.play_card("P0", "3C")


def test_first_card_must_be_2c() -> None:
    engine = make_engine(*MIX)
    with pytest.raises(IllegalMoveError):
        engine.play_card("P0", "AC")


def test_invalid_card_string_and_unknown_player() -> None:
    engine = make_engine(*MIX)
    with pytest.raises(ValueError):
        engine.play_card("P0", "ZZ")
    with pytest.raises(ValueError):
        engine.play_card("P9", "2C")
    with pytest.raises(ValueError):
        engine.get_legal_moves("P9")
    with pytest.raises(ValueError):
        engine.get_player_observation("P9")


def test_failed_move_does_not_change_state() -> None:
    engine = make_engine(*MIX)
    engine.play_card("P0", "2C")
    before = engine.get_player_observation("P1")
    with pytest.raises(IllegalMoveError):
        engine.play_card("P1", "5D")
    assert engine.get_player_observation("P1") == before


# ------------------------------------------------- end of deal / the moon


def test_shooting_the_moon() -> None:
    engine = make_engine(*MOON)
    play_out(engine)
    assert engine.is_over
    assert engine.current_player is None
    assert engine.points_taken == {"P0": 26, "P1": 0, "P2": 0, "P3": 0}
    assert engine.shot_the_moon == "P0"
    assert engine.final_scores == {"P0": 0, "P1": 26, "P2": 26, "P3": 26}
    obs = engine.get_player_observation("P1")
    assert obs.scores == {"P0": 0, "P1": 26, "P2": 26, "P3": 26}
    assert obs.game_over
    assert obs.legal_moves == []


def test_moon_final_move_reports_hand_over() -> None:
    engine = make_engine(*MOON)
    last = None
    while not engine.is_over:
        player = engine.current_player
        assert player is not None
        last = engine.play_card(player, engine.get_legal_moves(player)[0])
    assert last is not None
    assert last.hand_over
    assert last.trick_completed


def test_no_moon_when_points_are_split() -> None:
    engine = make_engine(*MIX)
    play_out(engine)
    raw = engine.points_taken
    assert sum(raw.values()) == 26
    if max(raw.values()) < 26:
        assert engine.shot_the_moon is None
        assert engine.final_scores == raw


def test_no_moves_after_deal_is_over() -> None:
    engine = make_engine(*MOON)
    play_out(engine)
    with pytest.raises(IllegalMoveError):
        engine.play_card("P0", "2C")
    assert all(engine.get_legal_moves(p) == [] for p in engine.player_ids)


def test_running_scores_visible_during_play() -> None:
    engine = make_engine(*FIVE)
    play(engine, "P0:2C P1:QC P2:TD P3:8S P4:QS")
    obs = engine.get_player_observation("P0")
    assert obs.scores == {"P0": 0, "P1": 13, "P2": 0, "P3": 0, "P4": 0}
    assert engine.final_scores is None


@pytest.mark.parametrize("players", [2, 3, 4, 5])
@pytest.mark.parametrize("seed", range(20))
def test_random_full_games_are_consistent(players: int, seed: int) -> None:
    engine = HeartsGameEngine(players, seed=seed)
    chooser = random.Random(seed)
    tricks = 0
    while not engine.is_over:
        player = engine.current_player
        assert player is not None
        legal = engine.get_legal_moves(player)
        assert legal
        obs = engine.get_player_observation(player)
        assert set(legal) <= set(obs.hand)
        result = engine.play_card(player, chooser.choice(legal))
        tricks += result.trick_completed
    deck_size = {2: 52, 3: 51, 4: 52, 5: 50}[players]
    assert tricks == deck_size // players
    raw = engine.points_taken
    assert sum(raw.values()) == 26
    final = engine.final_scores
    assert final is not None
    if max(raw.values()) == 26:
        assert sorted(final.values()) == [0] + [26] * (players - 1)
    else:
        assert final == raw
    assert all(not engine.get_player_observation(p).hand for p in engine.player_ids)
    assert len(engine.get_player_observation("P0").trick_history) == tricks


@pytest.mark.parametrize("seed", range(10))
def test_hearts_never_led_unbroken_unless_forced(seed: int) -> None:
    engine = HeartsGameEngine(4, seed=seed)
    chooser = random.Random(seed + 100)
    while not engine.is_over:
        player = engine.current_player
        assert player is not None
        obs = engine.get_player_observation(player)
        if not obs.current_trick and not obs.hearts_broken and obs.trick_number > 1:
            if any(not c.endswith("H") for c in obs.hand):
                assert all(not c.endswith("H") for c in obs.legal_moves)
        engine.play_card(player, chooser.choice(obs.legal_moves))


# ------------------------------------------------------------ observation


def test_observation_initial_state() -> None:
    engine = make_engine(*MIX)
    obs = engine.get_player_observation("P0")
    assert isinstance(obs, PlayerObservation)
    assert obs.player_id == "P0"
    assert obs.hand == ["2C", "TC", "AC", "2D", "3D", "4D", "2S", "3S", "4S", "5S", "2H", "3H", "4H"]
    assert obs.current_trick == []
    assert obs.trick_history == []
    assert obs.exposed_voids == {"P0": [], "P1": [], "P2": [], "P3": []}
    assert obs.hearts_broken is False
    assert obs.scores == {"P0": 0, "P1": 0, "P2": 0, "P3": 0}
    assert obs.legal_moves == ["2C"]


def test_observation_is_a_snapshot() -> None:
    engine = make_engine(*MIX)
    obs = engine.get_player_observation("P0")
    obs.hand.clear()
    obs.exposed_voids["P0"].append("C")
    obs.scores["P0"] = 99
    fresh = engine.get_player_observation("P0")
    assert len(fresh.hand) == 13
    assert fresh.exposed_voids["P0"] == []
    assert fresh.scores["P0"] == 0


def test_observation_shows_only_own_hand_and_legal_moves() -> None:
    engine = make_engine(*MIX)
    assert engine.get_player_observation("P1").legal_moves == []
    assert "2C" not in engine.get_player_observation("P1").hand


def test_icl_prompt_initial() -> None:
    engine = make_engine(*MIX)
    prompt = engine.get_player_observation("P0").to_icl_prompt()
    lines = prompt.splitlines()
    assert lines[0] == "HEARTS 4p | You: P0 | Trick 1 | Turn: P0 | Hearts broken: no"
    assert lines[1] == "Hand: 2C TC AC 2D 3D 4D 2S 3S 4S 5S 2H 3H 4H"
    assert lines[2] == "Trick: (empty)"
    assert lines[3] == "Legal: 2C"
    assert lines[4] == "Voids: P0:- P1:- P2:- P3:-"
    assert lines[5] == "Scores: P0=0 P1=0 P2=0 P3=0"
    assert lines[6] == "History: (none)"


def test_icl_prompt_midgame() -> None:
    engine = make_engine(*FIVE)
    play(engine, "P0:2C P1:QC P2:TD P3:8S P4:6H P1:KC P2:JD")
    prompt = engine.get_player_observation("P3").to_icl_prompt()
    lines = prompt.splitlines()
    assert lines[0] == "HEARTS 5p | You: P3 | Trick 2 | Turn: P3 | Hearts broken: yes"
    assert lines[1] == "Hand: 9S TS JS KS AS 2H 3H 4H 5H"
    assert lines[2] == "Trick: P1:KC P2:JD"
    assert lines[3] == "Legal: " + " ".join(engine.get_legal_moves("P3"))
    assert lines[4] == "Voids: P0:- P1:- P2:C P3:C P4:C"
    assert lines[5] == "Scores: P0=0 P1=1 P2=0 P3=0 P4=0"
    assert lines[6] == "History:"
    assert lines[7] == "T1: P0:2C, P1:QC, P2:TD, P3:8S, P4:6H -> Win:P1 (1pts)"


def test_icl_prompt_not_my_turn_has_empty_legal() -> None:
    engine = make_engine(*MIX)
    lines = engine.get_player_observation("P2").to_icl_prompt().splitlines()
    assert lines[3] == "Legal: -"


def test_icl_prompt_stays_compact_and_truncates_history() -> None:
    engine = HeartsGameEngine(3, seed=7)  # 17 tricks
    chooser = random.Random(7)
    for _ in range(16 * 3):
        player = engine.current_player
        assert player is not None
        engine.play_card(player, chooser.choice(engine.get_legal_moves(player)))
    assert len(engine.get_player_observation("P0").trick_history) == 16
    player = engine.current_player
    assert player is not None
    prompt = engine.get_player_observation(player).to_icl_prompt()
    lines = prompt.splitlines()
    assert len(lines) <= 20
    assert "History (last 8 of 16):" in lines
    assert lines[-1].startswith("T16:")
    assert lines[-8].startswith("T9:")


def test_icl_prompt_full_history_when_short() -> None:
    engine = make_engine(*MIX)
    play(engine, "P0:2C P1:3C P2:6C P3:9C")
    lines = engine.get_player_observation("P3").to_icl_prompt().splitlines()
    assert "History:" in lines
    assert "T1: P0:2C, P1:3C, P2:6C, P3:9C -> Win:P3 (0pts)" in lines


def test_icl_prompt_game_over() -> None:
    engine = make_engine(*MOON)
    play_out(engine)
    lines = engine.get_player_observation("P2").to_icl_prompt().splitlines()
    assert lines[0] == "HEARTS 4p | You: P2 | GAME OVER"
    assert "Final scores: P0=0 P1=26 P2=26 P3=26" in lines
    assert len(lines) <= 20


@pytest.mark.parametrize("players", [2, 3, 4, 5])
def test_icl_prompt_never_exceeds_20_lines(players: int) -> None:
    engine = HeartsGameEngine(players, seed=3)
    chooser = random.Random(3)
    while not engine.is_over:
        player = engine.current_player
        assert player is not None
        prompt = engine.get_player_observation(player).to_icl_prompt()
        assert len(prompt.splitlines()) <= 20
        engine.play_card(player, chooser.choice(engine.get_legal_moves(player)))
