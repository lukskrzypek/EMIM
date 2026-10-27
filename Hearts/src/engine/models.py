"""Card, suit, rank, and deck models."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from functools import total_ordering
from typing import Self


_INDEX_CACHE: dict[Enum, int] = {}


def _definition_index(member: Enum) -> int:
    try:
        return _INDEX_CACHE[member]
    except KeyError:
        index = _INDEX_CACHE[member] = list(type(member)).index(member)
        return index


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

    @property
    def value(self) -> int:
        """Numeric rank: 2..10, J=11, Q=12, K=13, A=14."""
        return _definition_index(self.rank) + 2

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


KING_PLAYER_COUNTS: tuple[int, ...] = (3, 4)
_KING_REMOVED_CODES: dict[int, frozenset[str]] = {3: frozenset({"2C"}), 4: frozenset()}


def king_deck(num_players: int) -> tuple[Card, ...]:
    """Sorted deck of the King game: 52 cards for 4 players, 51 (no ``2C``) for 3."""
    if num_players not in _KING_REMOVED_CODES:
        raise ValueError(f"Player count must be one of {KING_PLAYER_COUNTS}, got {num_players}")
    removed = _KING_REMOVED_CODES[num_players]
    return tuple(card for card in standard_deck() if str(card) not in removed)


def king_hand_size(num_players: int) -> int:
    """Cards per player = tricks per deal (13 for 4 players, 17 for 3)."""
    return len(king_deck(num_players)) // num_players
