"""Rodzaje rund i punkty karne (łatwo zmienić w słowniku poniżej)."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum

from .cards import Card

TOTAL_TRICKS = 13

# Wartości kar (jednostki umowne; liczy się proporcja, nie wartość bezwzględna).
PENALTY_TRICK = 20        # bez lew: każda lewa
PENALTY_HEART = 20        # bez kierów: każdy kier
PENALTY_QUEEN = 60        # bez dam: każda dama
PENALTY_KING_JACK = 30    # bez panów: każdy król i walet
PENALTY_KING_HEARTS = 150 # bez króla kierowego
PENALTY_SPECIAL_TRICK = 75  # bez 7. i ostatniej lewy


class RoundType(str, Enum):
    NO_TRICKS = "no_tricks"
    NO_HEARTS = "no_hearts"
    NO_QUEENS = "no_queens"
    NO_KINGS_JACKS = "no_kings_jacks"
    NO_KING_OF_HEARTS = "no_king_of_hearts"
    NO_SEVENTH_LAST = "no_seventh_last"
    ROBBER = "robber"  # rozbójnik: wszystko naraz
    HEARTS = "hearts"  # kierki jak w silniku Hearts: każdy kier 1 pkt, dama pik 13 pkt (2-5 graczy)


def _heart(c: Card) -> int:
    return PENALTY_HEART if c.suit == "h" else 0


def _queen(c: Card) -> int:
    return PENALTY_QUEEN if c.rank == "Q" else 0


def _king_jack(c: Card) -> int:
    return PENALTY_KING_JACK if c.rank in ("K", "J") else 0


def _king_hearts(c: Card) -> int:
    return PENALTY_KING_HEARTS if (c.rank == "K" and c.suit == "h") else 0


def _hearts_card(c: Card) -> int:
    """Punkty jak w silniku (engine.game.card_points): kier = 1, dama pik = 13."""
    if c.suit == "h":
        return 1
    return 13 if (c.rank == "Q" and c.suit == "s") else 0


def _none_card(c: Card) -> int:
    return 0


def _trick_every(n: int) -> int:
    return PENALTY_TRICK


def _trick_special(n: int) -> int:
    return PENALTY_SPECIAL_TRICK if n in (7, TOTAL_TRICKS) else 0


def _trick_none(n: int) -> int:
    return 0


@dataclass(frozen=True)
class RoundRules:
    card_penalty: Callable[[Card], int]
    trick_penalty: Callable[[int], int]  # numer lewy (1..13) -> kara za wzięcie jej


def get_rules(round_type: RoundType) -> RoundRules:
    if round_type == RoundType.NO_TRICKS:
        return RoundRules(_none_card, _trick_every)
    if round_type == RoundType.NO_HEARTS:
        return RoundRules(_heart, _trick_none)
    if round_type == RoundType.NO_QUEENS:
        return RoundRules(_queen, _trick_none)
    if round_type == RoundType.NO_KINGS_JACKS:
        return RoundRules(_king_jack, _trick_none)
    if round_type == RoundType.NO_KING_OF_HEARTS:
        return RoundRules(_king_hearts, _trick_none)
    if round_type == RoundType.NO_SEVENTH_LAST:
        return RoundRules(_none_card, _trick_special)
    if round_type == RoundType.ROBBER:
        return RoundRules(
            lambda c: _heart(c) + _queen(c) + _king_jack(c) + _king_hearts(c),
            lambda n: PENALTY_TRICK + _trick_special(n),
        )
    if round_type == RoundType.HEARTS:
        return RoundRules(_hearts_card, _trick_none)
    raise ValueError(f"Nieznany rodzaj rundy: {round_type}")
