"""Card, suit, rank, and deck models."""

from __future__ import annotations

import random
from dataclasses import dataclass
from enum import Enum
from functools import total_ordering
from typing import Self


def _definition_index(member: Enum) -> int:
    return list(type(member)).index(member)


@total_ordering
class Suit(Enum):
    """Suit symbol. Sort order follows the spec: C, D, S, H."""

    CLUBS = "C"
    DIAMONDS = "D"
    SPADES = "S"
    HEARTS = "H"

    def __lt__(self, other: object) -> bool:
        if not isinstance(other, Suit):
            return NotImplemented
        return _definition_index(self) < _definition_index(other)


@total_ordering
class Rank(Enum):
    """Rank symbol. Sort order is 2, 3, 4, 5, 6, 7, 8, 9, T, J, Q, K, A."""

    TWO = "2"
    THREE = "3"
    FOUR = "4"
    FIVE = "5"
    SIX = "6"
    SEVEN = "7"
    EIGHT = "8"
    NINE = "9"
    TEN = "T"
    JACK = "J"
    QUEEN = "Q"
    KING = "K"
    ACE = "A"

    def __lt__(self, other: object) -> bool:
        if not isinstance(other, Rank):
            return NotImplemented
        return _definition_index(self) < _definition_index(other)


_RANK_BY_SYMBOL: dict[str, Rank] = {rank.value: rank for rank in Rank}
_SUIT_BY_SYMBOL: dict[str, Suit] = {suit.value: suit for suit in Suit}


@total_ordering
@dataclass(frozen=True, slots=True)
class Card:
    """A single card. Sorts by suit (C, D, S, H), then by rank (2..A)."""

    suit: Suit
    rank: Rank

    @classmethod
    def parse(cls, value: str) -> Self:
        """Parse a 2-character code such as ``2C`` or ``QS``."""
        if not isinstance(value, str) or len(value) != 2:
            raise ValueError(f"Card notation must be exactly 2 characters, got {value!r}")
        rank = _RANK_BY_SYMBOL.get(value[0])
        suit = _SUIT_BY_SYMBOL.get(value[1])
        if rank is None or suit is None:
            raise ValueError(f"Invalid card notation: {value!r}")
        return cls(suit, rank)

    def __lt__(self, other: object) -> bool:
        if not isinstance(other, Card):
            return NotImplemented
        return (_definition_index(self.suit), _definition_index(self.rank)) < (
            _definition_index(other.suit),
            _definition_index(other.rank),
        )

    def __str__(self) -> str:
        return f"{self.rank.value}{self.suit.value}"


def standard_deck() -> list[Card]:
    """Return all 52 cards, sorted."""
    return sorted(Card(suit, rank) for suit in Suit for rank in Rank)


# Cards removed so the remaining deck splits evenly. See SPEC section 2.
_REMOVED_CODES: dict[int, frozenset[str]] = {
    2: frozenset(),
    3: frozenset({"2D"}),
    4: frozenset(),
    5: frozenset({"2D", "2S"}),
}


class Deck:
    """Deck prepared for 2, 3, 4, or 5 players, then dealt into sorted hands."""

    def __init__(self, num_players: int) -> None:
        if num_players not in _REMOVED_CODES:
            raise ValueError(f"Player count must be 2, 3, 4, or 5, got {num_players}")
        self.num_players: int = num_players
        removed = _REMOVED_CODES[num_players]
        self.cards: tuple[Card, ...] = tuple(
            card for card in standard_deck() if str(card) not in removed
        )

    @property
    def cards_per_player(self) -> int:
        return len(self.cards) // self.num_players

    def deal(self, rng: random.Random | None = None) -> list[list[Card]]:
        """Deal one card at a time. Shuffle first when ``rng`` is given.

        Each hand is returned sorted. The deck itself is left unchanged.
        """
        cards = list(self.cards)
        if rng is not None:
            rng.shuffle(cards)
        hands: list[list[Card]] = [[] for _ in range(self.num_players)]
        for index, card in enumerate(cards):
            hands[index % self.num_players].append(card)
        return [sorted(hand) for hand in hands]
