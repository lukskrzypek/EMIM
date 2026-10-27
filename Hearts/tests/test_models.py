"""Tests for card notation, ordering, and dealing."""

from __future__ import annotations

import pytest

from engine.models import Card, Rank, Suit, king_deck, king_hand_size

RANK_SYMBOLS = "23456789TJQKA"
SUIT_SYMBOLS = "CDSH"
ALL_CODES = [rank + suit for suit in SUIT_SYMBOLS for rank in RANK_SYMBOLS]


def test_rank_order_matches_spec() -> None:
    assert [rank.value for rank in Rank] == list(RANK_SYMBOLS)
    assert list(Rank) == sorted(Rank)


def test_suit_order_is_clubs_diamonds_spades_hearts() -> None:
    assert [suit.value for suit in Suit] == list(SUIT_SYMBOLS)
    assert list(Suit) == sorted(Suit)


def test_rank_and_suit_seniority() -> None:
    assert Rank.TWO < Rank.THREE < Rank.TEN < Rank.JACK < Rank.QUEEN < Rank.KING < Rank.ACE
    assert Suit.CLUBS < Suit.DIAMONDS < Suit.SPADES < Suit.HEARTS


@pytest.mark.parametrize("code", ALL_CODES)
def test_parse_and_serialize_roundtrip(code: str) -> None:
    card = Card.parse(code)
    assert str(card) == code
    assert card.rank.value == code[0]
    assert card.suit.value == code[1]


def test_parse_known_examples() -> None:
    assert Card.parse("2C") == Card(Suit.CLUBS, Rank.TWO)
    assert Card.parse("QS") == Card(Suit.SPADES, Rank.QUEEN)
    assert str(Card.parse("TD")) == "TD"
    assert str(Card.parse("AH")) == "AH"


@pytest.mark.parametrize(
    "bad",
    ["", "2", "2CX", "1C", "2X", "10C", "2c", "qs", " QC", "2C ", "XH", "HH"],
)
def test_parse_rejects_invalid_notation(bad: str) -> None:
    with pytest.raises(ValueError):
        Card.parse(bad)


def test_parse_rejects_non_string() -> None:
    with pytest.raises(ValueError):
        Card.parse(2)  # type: ignore[arg-type]


def test_cards_sort_by_suit_then_rank() -> None:
    cards = [Card.parse(code) for code in ["QS", "2C", "KC", "8D", "AH", "3C"]]
    assert [str(card) for card in sorted(cards)] == ["2C", "3C", "KC", "8D", "QS", "AH"]


def test_rank_seniority_within_a_suit() -> None:
    cards = [Card.parse(rank + "H") for rank in "AKQJT98765432"]
    assert [card.rank.value for card in sorted(cards)] == list(RANK_SYMBOLS)


def test_standard_deck_is_fully_ordered() -> None:
    shuffled = [Card.parse(code) for code in reversed(ALL_CODES)]
    assert [str(card) for card in sorted(shuffled)] == ALL_CODES


def test_card_equality_and_hash() -> None:
    queen = Card.parse("QS")
    same = Card(Suit.SPADES, Rank.QUEEN)
    assert queen == same
    assert hash(queen) == hash(same)
    assert len({queen, same, Card.parse("2C")}) == 2
    assert not queen < queen


@pytest.mark.parametrize(
    ("num_players", "removed", "hand_size"),
    [(3, {"2C"}, 17), (4, set(), 13)],
)
def test_king_deck_per_player_count(num_players: int, removed: set[str], hand_size: int) -> None:
    deck = king_deck(num_players)
    codes = [str(card) for card in deck]

    assert len(codes) == num_players * hand_size
    assert len(set(codes)) == len(codes)
    assert set(codes) == set(ALL_CODES) - removed
    assert list(deck) == sorted(deck)
    assert king_hand_size(num_players) == hand_size


@pytest.mark.parametrize("num_players", [0, 1, 2, 5, 6, -1, 52])
def test_king_deck_rejects_unsupported_player_count(num_players: int) -> None:
    with pytest.raises(ValueError):
        king_deck(num_players)


@pytest.mark.parametrize("value, rank", [(2, "2"), (10, "T"), (11, "J"), (14, "A")])
def test_card_value(value: int, rank: str) -> None:
    assert Card.parse(f"{rank}H").value == value