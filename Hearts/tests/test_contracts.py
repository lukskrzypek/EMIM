"""Contract rules (SPEC.md sections 2-3): penalties, legal moves, trick winner."""

from __future__ import annotations

import random

import pytest

from engine.contracts import (
    CONTRACT_ORDER,
    HEART_LEAD_RESTRICTED,
    GameContract,
    card_penalty,
    contract_total_penalty,
    evaluate_trick_penalty,
    legal_cards,
    total_tricks,
    trick_number_penalty,
    trick_winner,
)
from engine.models import Card, king_deck, king_hand_size

C = Card.parse
NT, NH, NQ, NM, NK, N7, RB = (
    GameContract.NO_TRICKS,
    GameContract.NO_HEARTS,
    GameContract.NO_QUEENS,
    GameContract.NO_MEN,
    GameContract.NO_KING_OF_HEARTS,
    GameContract.NO_7TH_AND_LAST,
    GameContract.ROBBER,
)


def cards(spec: str) -> list[Card]:
    return [C(code) for code in spec.split()]


def trick(spec: str) -> list[tuple[str, Card]]:
    """``"P0:2C P1:3C"`` -> [("P0", 2C), ("P1", 3C)]."""
    return [(token.split(":")[0], C(token.split(":")[1])) for token in spec.split()]


# ------------------------------------------------------------------ models


def test_card_value_range() -> None:
    assert [C(f"{r}S").value for r in "23456789TJQKA"] == list(range(2, 15))


def test_king_deck_sizes() -> None:
    assert len(king_deck(4)) == 52 and king_hand_size(4) == 13
    three = king_deck(3)
    assert len(three) == 51 and king_hand_size(3) == 17
    assert C("2C") not in three and C("2D") in three
    assert len(set(three)) == 51
    assert (total_tricks(4), total_tricks(3)) == (13, 17)


@pytest.mark.parametrize("players", [2, 5, 0])
def test_king_deck_rejects_other_player_counts(players: int) -> None:
    with pytest.raises(ValueError):
        king_deck(players)


def test_contract_order_is_the_spec_order() -> None:
    assert [c.value for c in CONTRACT_ORDER] == [
        "NO_TRICKS",
        "NO_HEARTS",
        "NO_QUEENS",
        "NO_MEN",
        "NO_KING_OF_HEARTS",
        "NO_7TH_AND_LAST",
        "ROBBER",
    ]


# --------------------------------------------------------------- penalties


@pytest.mark.parametrize(
    ("contract", "code", "expected"),
    [
        (NT, "AH", 0),
        (NH, "2H", 20),
        (NH, "KH", 20),
        (NH, "QS", 0),
        (NQ, "QS", 60),
        (NQ, "QH", 60),
        (NQ, "KS", 0),
        (NM, "KC", 30),
        (NM, "JD", 30),
        (NM, "QD", 0),
        (NM, "KH", 30),
        (NK, "KH", 150),
        (NK, "KS", 0),
        (NK, "AH", 0),
        (N7, "KH", 0),
        (RB, "KH", 200),  # heart 20 + king 30 + KH 150
        (RB, "QH", 80),  # heart 20 + queen 60
        (RB, "JH", 50),
        (RB, "KS", 30),
        (RB, "QS", 60),
        (RB, "9D", 0),
    ],
)
def test_card_penalty(contract: GameContract, code: str, expected: int) -> None:
    assert card_penalty(C(code), contract) == expected


@pytest.mark.parametrize(
    ("contract", "trick_num", "expected"),
    [
        (NT, 1, 20),
        (NT, 13, 20),
        (NH, 7, 0),
        (NQ, 13, 0),
        (NM, 7, 0),
        (NK, 13, 0),
        (N7, 1, 0),
        (N7, 6, 0),
        (N7, 7, 75),
        (N7, 8, 0),
        (N7, 13, 75),
        (RB, 1, 20),
        (RB, 7, 95),
        (RB, 13, 95),
    ],
)
def test_trick_number_penalty_four_players(
    contract: GameContract, trick_num: int, expected: int
) -> None:
    assert trick_number_penalty(trick_num, 13, contract) == expected


def test_last_trick_depends_on_player_count() -> None:
    assert trick_number_penalty(13, 17, N7) == 0
    assert trick_number_penalty(17, 17, N7) == 75
    assert trick_number_penalty(17, 17, RB) == 95
    assert trick_number_penalty(7, 17, N7) == 75


def test_evaluate_trick_penalty_adds_cards_and_trick_number() -> None:
    cards_taken = cards("KH QH 2S 3S")
    assert evaluate_trick_penalty(cards_taken, 3, NH) == 40
    assert evaluate_trick_penalty(cards_taken, 3, NT) == 20
    assert evaluate_trick_penalty(cards_taken, 3, NQ) == 60
    assert evaluate_trick_penalty(cards_taken, 3, NM) == 30
    assert evaluate_trick_penalty(cards_taken, 3, NK) == 150
    assert evaluate_trick_penalty(cards_taken, 7, N7) == 75
    # ROBBER: trick 20 + trick 7 75 + KH 200 + QH 80 = 375
    assert evaluate_trick_penalty(cards_taken, 7, RB) == 375
    assert evaluate_trick_penalty(cards_taken, 7, RB, 13) == 375
    assert evaluate_trick_penalty(cards_taken, 13, RB, 17) == 300  # 13 is not the last of 17


@pytest.mark.parametrize(
    ("contract", "four", "three"),
    [
        (NT, 260, 340),
        (NH, 260, 260),
        (NQ, 240, 240),
        (NM, 240, 240),
        (NK, 150, 150),
        (N7, 150, 150),
        (RB, 1300, 1380),
    ],
)
def test_contract_totals_match_spec(contract: GameContract, four: int, three: int) -> None:
    assert contract_total_penalty(contract, 4) == four
    assert contract_total_penalty(contract, 3) == three


def test_robber_is_the_sum_of_the_other_contracts() -> None:
    for players in (3, 4):
        others = sum(contract_total_penalty(c, players) for c in CONTRACT_ORDER if c is not RB)
        assert contract_total_penalty(RB, players) == others


# -------------------------------------------------------------- legal moves


def test_lead_is_free_in_unrestricted_contracts() -> None:
    hand = cards("2H KH 3C")
    for contract in (NT, NQ, NM, N7):
        assert legal_cards(hand, [], contract, king_of_hearts_played=False) == sorted(hand)


@pytest.mark.parametrize("contract", sorted(HEART_LEAD_RESTRICTED, key=lambda c: c.value))
def test_hearts_cannot_be_led_while_holding_other_suits(contract: GameContract) -> None:
    hand = cards("2H KH 3C 9S")
    legal = legal_cards(hand, [], contract, king_of_hearts_played=False)
    assert legal == sorted(cards("3C 9S"))


@pytest.mark.parametrize("contract", sorted(HEART_LEAD_RESTRICTED, key=lambda c: c.value))
def test_hearts_lead_allowed_with_only_hearts(contract: GameContract) -> None:
    hand = cards("2H KH AH")
    assert legal_cards(hand, [], contract, king_of_hearts_played=False) == sorted(hand)


@pytest.mark.parametrize("contract", sorted(HEART_LEAD_RESTRICTED, key=lambda c: c.value))
def test_hearts_lead_allowed_after_king_of_hearts_was_played(contract: GameContract) -> None:
    hand = cards("2H 3C")
    assert legal_cards(hand, [], contract, king_of_hearts_played=True) == sorted(hand)


def test_heart_restriction_does_not_apply_when_following() -> None:
    legal = legal_cards(cards("2H 3H 4C"), trick("P0:9H"), NK, king_of_hearts_played=False)
    assert legal == sorted(cards("2H 3H"))


@pytest.mark.parametrize("contract", list(CONTRACT_ORDER))
def test_must_follow_suit(contract: GameContract) -> None:
    legal = legal_cards(cards("2C 9C AD KH"), trick("P0:5C"), contract, king_of_hearts_played=False)
    assert legal == sorted(cards("2C 9C"))


@pytest.mark.parametrize("contract", list(CONTRACT_ORDER))
def test_void_player_may_discard_anything(contract: GameContract) -> None:
    hand = cards("2D KH 5C")
    legal = legal_cards(hand, trick("P0:3S"), contract, king_of_hearts_played=False)
    assert legal == sorted(hand)


def test_no_first_trick_or_hearts_broken_restrictions() -> None:
    # Classic Hearts rules (2C start, no points on trick 1, hearts broken) are gone.
    assert legal_cards(cards("2H QS 5C"), trick("P0:3D"), NT, king_of_hearts_played=False) == sorted(
        cards("2H QS 5C")
    )
    assert legal_cards(cards("2H QS"), [], NQ, king_of_hearts_played=False) == sorted(cards("2H QS"))


# ------------------------------------------------------------ trick winner


def test_trick_winner_is_highest_card_of_led_suit() -> None:
    assert trick_winner(trick("P0:5C P1:9C P2:AD P3:7C")) == "P1"
    assert trick_winner(trick("P2:2H P3:KS P0:3H P1:QH")) == "P1"


def test_off_suit_cards_never_win() -> None:
    assert trick_winner(trick("P0:2C P1:AS P2:AH P3:AD")) == "P0"


def test_trick_winner_with_three_players() -> None:
    assert trick_winner(trick("P1:TD P2:JD P0:9D")) == "P2"


# ------------------------------------------- whole-deal invariants (random)


def _random_deal_total(contract: GameContract, players: int, seed: int) -> int:
    rng = random.Random(seed)
    deck = list(king_deck(players))
    rng.shuffle(deck)
    size = king_hand_size(players)
    hands = {f"P{i}": sorted(deck[i * size : (i + 1) * size]) for i in range(players)}
    ids = list(hands)
    leader = rng.choice(ids)
    king_played = False
    total = 0
    for number in range(1, size + 1):
        played: list[tuple[str, Card]] = []
        order = ids[ids.index(leader) :] + ids[: ids.index(leader)]
        for pid in order:
            legal = legal_cards(hands[pid], played, contract, king_of_hearts_played=king_played)
            assert legal, f"{pid} has no legal move"
            card = rng.choice(legal)
            hands[pid].remove(card)
            played.append((pid, card))
            king_played = king_played or card.suit.value == "H" and card.rank.value == "K"
        leader = trick_winner(played)
        total += evaluate_trick_penalty([c for _, c in played], number, contract, size)
    assert not any(hands.values())
    return total


@pytest.mark.parametrize("players", [3, 4])
@pytest.mark.parametrize("contract", list(CONTRACT_ORDER))
def test_random_deals_hand_out_the_constant_total(contract: GameContract, players: int) -> None:
    expected = contract_total_penalty(contract, players)
    for seed in range(25):
        assert _random_deal_total(contract, players, seed) == expected
