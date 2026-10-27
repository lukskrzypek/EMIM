"""GameState: a whole King match as a deterministic state machine (SPEC.md, sections 2-4)."""

from __future__ import annotations

import random

import pytest

from engine.contracts import CONTRACT_ORDER, GameContract, contract_total_penalty
from engine.models import Card, Suit, king_deck
from engine.state import GameState, IllegalMoveError, PlayResult, schedule

NT = GameContract.NO_TRICKS


def hand(spec: str) -> list[str]:
    """Parse ``"C2TA D234"`` (suit letter followed by rank letters) into card codes."""
    cards: list[str] = []
    for token in spec.split():
        suit, ranks = token[0], token[1:]
        cards.extend(rank + suit for rank in ranks)
    return sorted(cards, key=Card.parse)


# 4 players, mixed hands. Led from P0 with clubs, P3 wins with 9C.
MIX = (
    "C2TA D234 S2345 H234",
    "C345 D5678 S678 H567",
    "C678 D9TJQ S9TJ H89T",
    "C9JQK DKA SQKA HJQKA",
)


def contract_start(contract: GameContract, players: int = 4) -> int:
    """Deal number at which ``contract`` is played for the first time."""
    return CONTRACT_ORDER.index(contract) * players + 1


def mix_state(contract: GameContract = NT, first_declarer: int = 0) -> GameState:
    return GameState.new(
        4,
        hands=[hand(s) for s in MIX],
        first_declarer=first_declarer,
        start_deal=contract_start(contract),
    )


def play(state: GameState, moves: str) -> PlayResult:
    """Play ``"P0:2C P1:3C"`` in order and return the last result."""
    result: PlayResult | None = None
    for token in moves.split():
        player, card = token.split(":")
        result = state.play_card(player, card)
    assert result is not None
    return result


def play_out(state: GameState, rng: random.Random) -> int:
    """Random legal play to the end of the match; returns the number of moves."""
    moves = 0
    while not state.is_over:
        player = state.current_player
        assert player is not None
        legal = state.get_legal_moves(player)
        assert legal, f"{player} has no legal moves"
        state.play_card(player, rng.choice(legal))
        moves += 1
    return moves


# ------------------------------------------------------------------ creation


@pytest.mark.parametrize("players", [1, 2, 5, 6])
def test_unsupported_player_counts(players: int) -> None:
    with pytest.raises(ValueError):
        GameState.new(players)


@pytest.mark.parametrize(("players", "size", "deals"), [(4, 13, 28), (3, 17, 21)])
def test_new_match_shape(players: int, size: int, deals: int) -> None:
    state = GameState.new(players, seed=1)
    assert state.num_players == players
    assert state.total_deals == deals
    assert state.total_tricks == size
    assert state.deal_number == 1 and state.trick_number == 1
    assert state.current_contract is NT
    assert set(state.hands) == set(state.player_ids)
    assert all(len(h) == size for h in state.hands.values())
    dealt = [c for h in state.hands.values() for c in h]
    assert len(set(dealt)) == len(dealt) == players * size
    assert set(dealt) == set(king_deck(players))
    assert state.scores == dict.fromkeys(state.player_ids, 0)
    assert state.total_scores == dict.fromkeys(state.player_ids, 0)
    assert not state.is_over and state.winners == [] and state.final_scores is None


def test_three_players_play_without_two_of_clubs() -> None:
    state = GameState.new(3, seed=5)
    assert Card.parse("2C") not in [c for h in state.hands.values() for c in h]


def test_declarer_leads_the_first_trick() -> None:
    for first in range(4):
        state = GameState.new(4, seed=3, first_declarer=first)
        assert state.declarer == f"P{first}"
        assert state.lead_player == state.current_player == f"P{first}"


def test_first_declarer_is_random_but_seeded() -> None:
    picks = {GameState.new(4, seed=s).declarer for s in range(40)}
    assert picks == {"P0", "P1", "P2", "P3"}
    assert GameState.new(4, seed=7).declarer == GameState.new(4, seed=7).declarer


def test_same_seed_same_deal_different_seed_differs() -> None:
    a, b, c = GameState.new(4, seed=11), GameState.new(4, seed=11), GameState.new(4, seed=12)
    assert a.hands == b.hands
    assert a.hands != c.hands


def test_bad_provided_hands_are_rejected() -> None:
    good = [hand(s) for s in MIX]
    with pytest.raises(ValueError):
        GameState.new(4, hands=good[:3])
    dup = [list(h) for h in good]
    dup[1][0] = dup[0][0]
    with pytest.raises(ValueError):
        GameState.new(4, hands=dup)
    short = [list(h) for h in good]
    short[0].pop()
    with pytest.raises(ValueError):
        GameState.new(4, hands=short)
    with pytest.raises(ValueError):
        GameState.new(4, start_deal=29)
    with pytest.raises(ValueError):
        GameState.new(4, first_declarer=4)


# ------------------------------------------------------------------ schedule


@pytest.mark.parametrize("players", [3, 4])
def test_schedule_gives_every_player_every_contract_once(players: int) -> None:
    for first in range(players):
        plan = schedule(players, first)
        assert len(plan) == players * 7
        assert len(set(plan)) == len(plan)
        assert {(c, f"P{p}") for c in CONTRACT_ORDER for p in range(players)} == set(plan)
        declarers = [int(d[1:]) for _, d in plan]
        assert all((b - a) % players == 1 for a, b in zip(declarers, declarers[1:]))
        assert declarers[0] == first
        assert [c for c, _ in plan] == [c for c in CONTRACT_ORDER for _ in range(players)]


@pytest.mark.parametrize("players", [3, 4])
def test_match_follows_the_schedule(players: int) -> None:
    state = GameState.new(players, seed=21)
    plan = schedule(players, state.first_declarer)
    rng = random.Random(1)
    seen: list[tuple[GameContract, str]] = []
    while not state.is_over:
        if state.trick_number == 1 and not state.current_trick:
            seen.append((state.current_contract, state.declarer))
            assert state.lead_player == state.declarer
            assert state.deal_number == len(seen)
        player = state.current_player
        assert player is not None
        state.play_card(player, rng.choice(state.get_legal_moves(player)))
    assert seen == plan
    assert [(r.contract, r.declarer) for r in state.deal_results] == plan


# ------------------------------------------------------------------- tricks


def test_first_trick_and_winner_leads_next() -> None:
    state = mix_state()
    result = play(state, "P0:2C P1:3C P2:6C P3:9C")
    assert result.trick_completed and result.trick_winner == "P3"
    assert result.trick_points == 20 and not result.deal_over and not result.game_over
    assert state.scores["P3"] == 20 and sum(state.scores.values()) == 20
    assert state.trick_number == 2
    assert state.lead_player == state.current_player == "P3"
    assert state.current_trick == []
    assert [r.summary() for r in state.trick_history] == [
        "T1: P0:2C, P1:3C, P2:6C, P3:9C -> Win:P3 (20pts)"
    ]


def test_off_suit_card_never_wins_and_records_void() -> None:
    state = mix_state()
    state.hands["P1"] = [c for c in state.hands["P1"] if c.suit is not Suit.CLUBS]  # P1 is void
    result = play(state, "P0:2C P1:5D P2:6C P3:9C")
    assert result.trick_winner == "P3"
    assert "C" not in state.exposed_voids["P0"]
    assert state.exposed_voids["P1"] == ["C"]
    assert state.voids["P1"] == {Suit.CLUBS}


def test_play_follows_clockwise_order() -> None:
    state = mix_state(first_declarer=2)
    assert state.declarer == "P2"
    first = state.get_legal_moves("P2")[0]
    state.play_card("P2", first)
    assert state.current_player == "P3"
    legal = state.get_legal_moves("P3")
    state.play_card("P3", legal[0])
    assert state.current_player == "P0"


def test_card_can_be_given_as_card_or_string() -> None:
    state = mix_state()
    state.play_card("P0", Card.parse("2C"))
    state.play_card("P1", "3C")
    assert [str(c) for _, c in state.current_trick] == ["2C", "3C"]


def test_illegal_moves_are_rejected() -> None:
    state = mix_state()
    with pytest.raises(IllegalMoveError, match="turn"):
        state.play_card("P1", "3C")
    with pytest.raises(IllegalMoveError, match="hold"):
        state.play_card("P0", "KS")
    with pytest.raises(ValueError):
        state.play_card("P9", "2C")
    with pytest.raises(ValueError):
        state.play_card("P0", "ZZ")
    state.play_card("P0", "2C")
    with pytest.raises(IllegalMoveError, match="legal"):
        state.play_card("P1", "5D")  # P1 holds clubs and must follow suit
    assert state.get_legal_moves("P0") == []  # not P0's turn any more
    assert state.get_legal_moves("P1") == [Card.parse(c) for c in ("3C", "4C", "5C")]
    with pytest.raises(ValueError):
        state.get_legal_moves("P9")


def test_king_of_hearts_flag_is_set_when_played() -> None:
    state = mix_state()  # NO_TRICKS: leading hearts is free
    assert not state.king_of_hearts_played
    result = play(state, "P0:2H P1:5H P2:8H P3:KH")
    assert state.king_of_hearts_played and result.trick_winner == "P3"


@pytest.mark.parametrize(
    "contract",
    [GameContract.NO_HEARTS, GameContract.NO_KING_OF_HEARTS, GameContract.ROBBER],
)
def test_heart_lead_restriction_in_state(contract: GameContract) -> None:
    state = mix_state(contract)
    assert state.current_contract is contract and state.declarer == "P0"
    legal = state.get_legal_moves("P0")
    assert legal and all(c.suit is not Suit.HEARTS for c in legal)
    with pytest.raises(IllegalMoveError):
        state.play_card("P0", "2H")
    state.king_of_hearts_played = True
    assert Card.parse("2H") in state.get_legal_moves("P0")


@pytest.mark.parametrize(
    "contract", [GameContract.NO_TRICKS, GameContract.NO_QUEENS, GameContract.NO_MEN]
)
def test_hearts_can_be_led_in_unrestricted_contracts(contract: GameContract) -> None:
    state = mix_state(contract)
    assert Card.parse("2H") in state.get_legal_moves("P0")


def test_trick_penalty_method_matches_contract_rules() -> None:
    state = mix_state(GameContract.ROBBER)
    cards = [Card.parse(c) for c in ("KH", "2S", "3S", "4S")]
    assert state.evaluate_trick_penalty(cards, 7, GameContract.ROBBER) == 20 + 75 + 200
    assert state.evaluate_trick_penalty(cards, 7, GameContract.NO_TRICKS) == 20


# --------------------------------------------------------------- deal / match


def test_deal_ends_after_all_tricks_and_next_deal_starts() -> None:
    state = GameState.new(4, seed=2, first_declarer=1)
    rng = random.Random(3)
    results: list[PlayResult] = []
    while state.deal_number == 1:
        player = state.current_player
        assert player is not None
        results.append(state.play_card(player, rng.choice(state.get_legal_moves(player))))
    last = results[-1]
    assert last.deal_over and not last.game_over and last.trick_completed
    assert last.deal_number == 1
    assert last.deal_scores is not None and sum(last.deal_scores.values()) == 260
    assert sum(r.deal_over for r in results) == 1
    assert len(results) == 52
    # The state is already at the start of deal 2 (NO_TRICKS again, next declarer).
    assert state.deal_number == 2 and state.current_contract is NT
    assert state.declarer == "P2" and state.current_player == "P2"
    assert state.trick_number == 1 and state.trick_history == [] and state.played_cards == []
    assert state.scores == dict.fromkeys(state.player_ids, 0)
    assert state.total_scores == last.deal_scores
    assert all(len(h) == 13 for h in state.hands.values())
    assert len(state.deal_results) == 1 and state.deal_results[0].scores == last.deal_scores


def test_last_deal_ends_the_match() -> None:
    state = GameState.new(4, seed=8, start_deal=28)
    assert state.current_contract is GameContract.ROBBER
    rng = random.Random(0)
    result = None
    while not state.is_over:
        player = state.current_player
        assert player is not None
        result = state.play_card(player, rng.choice(state.get_legal_moves(player)))
    assert result is not None and result.deal_over and result.game_over
    assert state.current_player is None and state.is_over
    assert state.final_scores == state.total_scores
    assert sum(state.total_scores.values()) == 1300
    assert state.scores == result.deal_scores  # the finished deal stays visible
    assert state.winners == [p for p, v in state.total_scores.items() if v == min(state.total_scores.values())]
    assert all(state.get_legal_moves(p) == [] for p in state.player_ids)
    with pytest.raises(IllegalMoveError, match="over"):
        state.play_card("P0", "2C")


def test_manual_advance_keeps_the_finished_deal_visible() -> None:
    state = GameState.new(4, seed=2, first_declarer=1)
    state.auto_advance = False
    rng = random.Random(3)
    result = None
    while not state.deal_finished:
        player = state.current_player
        assert player is not None
        result = state.play_card(player, rng.choice(state.get_legal_moves(player)))
    assert result is not None and result.deal_over and not result.game_over
    assert state.deal_number == 1 and state.current_player is None and not state.is_over
    assert all(not h for h in state.hands.values()) and state.current_trick == []
    assert state.scores == result.deal_scores == state.total_scores
    assert len(state.trick_history) == 13
    assert state.get_player_observation("P0").legal_moves == []
    with pytest.raises(IllegalMoveError, match="start_next_deal"):
        state.play_card("P1", "2C")
    state.start_next_deal()
    assert state.deal_number == 2 and not state.deal_finished
    assert state.current_player == state.declarer == "P2"
    assert state.scores == dict.fromkeys(state.player_ids, 0) and state.trick_history == []
    with pytest.raises(IllegalMoveError):
        state.start_next_deal()  # nothing finished any more


def test_manual_advance_still_ends_the_match() -> None:
    state = GameState.new(4, seed=2, start_deal=28)
    state.auto_advance = False
    play_out(state, random.Random(1))
    assert state.is_over and state.deal_finished
    with pytest.raises(IllegalMoveError):
        state.start_next_deal()


def test_winners_lowest_total_with_ties() -> None:
    state = GameState.new(4, seed=1)
    state.match_over = True
    state.total_scores = {"P0": 300, "P1": 120, "P2": 120, "P3": 400}
    assert state.winners == ["P1", "P2"]
    state.total_scores = {"P0": 300, "P1": 120, "P2": 150, "P3": 400}
    assert state.winners == ["P1"]


@pytest.mark.parametrize("players", [3, 4])
def test_full_random_matches_keep_the_invariants(players: int) -> None:
    expected_moves = players * 7 * players * (13 if players == 4 else 17)
    for seed in range(4):
        state = GameState.new(players, seed=seed)
        plan = schedule(players, state.first_declarer)
        moves = play_out(state, random.Random(seed))
        assert moves == expected_moves
        assert state.is_over and state.deal_number == state.total_deals
        assert len(state.deal_results) == players * 7
        for result, (contract, _) in zip(state.deal_results, plan, strict=True):
            assert sum(result.scores.values()) == contract_total_penalty(contract, players)
        assert sum(state.total_scores.values()) == sum(
            contract_total_penalty(c, players) for c, _ in plan
        )
        for pid in state.player_ids:
            assert state.total_scores[pid] == sum(r.scores[pid] for r in state.deal_results)
        assert state.winners and all(
            state.total_scores[w] == min(state.total_scores.values()) for w in state.winners
        )


def test_no_card_is_played_twice_in_a_deal() -> None:
    state = GameState.new(4, seed=4)
    rng = random.Random(4)
    while state.deal_number == 1:
        player = state.current_player
        assert player is not None
        state.play_card(player, rng.choice(state.get_legal_moves(player)))
    # deal 2 has just been dealt: nothing is played yet
    assert state.played_cards == []
    played: list[Card] = []
    while state.deal_number == 2:
        player = state.current_player
        assert player is not None
        before = len(state.played_cards)
        state.play_card(player, rng.choice(state.get_legal_moves(player)))
        if state.deal_number == 2:
            assert len(state.played_cards) == before + 1
            played = [c for _, c in state.played_cards]
            assert len(set(played)) == len(played)


def test_same_seed_and_moves_reproduce_the_match() -> None:
    def run() -> tuple[dict[str, int], list[str]]:
        state = GameState.new(4, seed=99)
        rng = random.Random(5)
        order: list[str] = []
        while not state.is_over:
            player = state.current_player
            assert player is not None
            card = rng.choice(state.get_legal_moves(player))
            order.append(f"{player}:{card}")
            state.play_card(player, card)
        return state.total_scores, order

    assert run() == run()


# --------------------------------------------------------------------- clone


def test_clone_is_independent() -> None:
    state = mix_state()
    play(state, "P0:2C P1:3C")
    twin = state.clone()
    assert twin.hands == state.hands and twin.current_trick == state.current_trick
    play(twin, "P2:6C P3:9C")
    twin.hands["P3"].clear()
    twin.voids["P0"].add(Suit.SPADES)
    twin.total_scores["P0"] = 5
    assert [str(c) for _, c in state.current_trick] == ["2C", "3C"]
    assert state.current_player == "P2" and state.trick_number == 1
    assert len(state.hands["P3"]) == 13 and state.voids["P0"] == set()
    assert state.total_scores["P0"] == 0 and state.trick_history == []
    assert twin.trick_number == 2


def test_clone_can_be_played_to_the_end() -> None:
    state = GameState.new(4, seed=6, start_deal=28)
    twin = state.clone()
    play_out(twin, random.Random(1))
    assert twin.is_over and not state.is_over
    assert len(state.hands["P0"]) == 13
