"""Karty: parsowanie zapisu typu "Qs", "10h", "Ad", "2c"."""
from __future__ import annotations

import re
from dataclasses import dataclass

RANKS = ["2", "3", "4", "5", "6", "7", "8", "9", "10", "J", "Q", "K", "A"]
SUITS = ["s", "h", "d", "c"]  # spades, hearts, diamonds, clubs
_RANK_VALUE = {r: i + 2 for i, r in enumerate(RANKS)}
_CARD_RE = re.compile(r"^(10|[2-9]|[JQKATjqkat])([shdcSHDC])$")


@dataclass(frozen=True)
class Card:
    rank: str
    suit: str

    @property
    def value(self) -> int:
        return _RANK_VALUE[self.rank]

    def __str__(self) -> str:
        return f"{self.rank}{self.suit}"


def parse_card(text: str) -> Card:
    m = _CARD_RE.match(text.strip())
    if not m:
        raise ValueError(f"Nieprawidłowa karta: {text!r} (oczekiwano np. 'Qs', '10h', 'Ad')")
    rank, suit = m.groups()
    rank = rank.upper()
    if rank == "T":     #Zamiana T na 10
        rank = "10"
    return Card(rank, suit.lower())


# Karty usuwane z talii, żeby rozdać po równo (SPEC.md, sekcja 2).
_REMOVED: dict[int, tuple[Card, ...]] = {
    2: (),
    3: (Card("2", "d"),),
    4: (),
    5: (Card("2", "d"), Card("2", "s")),
}
SUPPORTED_PLAYER_COUNTS = tuple(_REMOVED)


def full_deck(num_players: int = 4) -> list[Card]:
    """Talia dla danej liczby graczy (2-5)."""
    if num_players not in _REMOVED:
        raise ValueError(f"Liczba graczy musi być jedną z {SUPPORTED_PLAYER_COUNTS}, jest {num_players}.")
    removed = set(_REMOVED[num_players])
    return [Card(r, s) for s in SUITS for r in RANKS if Card(r, s) not in removed]


def total_tricks(num_players: int = 4) -> int:
    """Liczba lew w rozdaniu = liczba kart na gracza."""
    return len(full_deck(num_players)) // num_players
