"""Kary kontraktu dla oceny ruchów: cienka nakładka na reguły silnika (``engine.contracts``).

Nie ma tu własnych wartości kar: moduł zamienia kartę zapisu oceny (``Qs``, ``10h``)
na kartę silnika i pyta silnik, ile kosztuje jej wzięcie.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from functools import lru_cache

from engine.contracts import GameContract, card_penalty, total_tricks, trick_number_penalty
from engine.models import Card as EngineCard

from .cards import Card


@lru_cache(maxsize=None)
def _penalty(rank: str, suit: str, contract: GameContract) -> int:
    code = ("T" if rank == "10" else rank) + suit.upper()
    return card_penalty(EngineCard.parse(code), contract)


@dataclass(frozen=True)
class RoundRules:
    card_penalty: Callable[[Card], int]
    trick_penalty: Callable[[int], int]  # numer lewy (1..13 lub 1..17) -> kara za wzięcie jej


def get_rules(contract: GameContract, num_players: int = 4) -> RoundRules:
    tricks = total_tricks(num_players)
    return RoundRules(
        card_penalty=lambda c: _penalty(c.rank, c.suit, contract),
        trick_penalty=lambda n: trick_number_penalty(n, tricks, contract),
    )
