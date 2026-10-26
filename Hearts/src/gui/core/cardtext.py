"""Human-readable card text for logs and buttons (``TH`` -> ``10♥``)."""

from __future__ import annotations

SUIT_SYMBOLS = {"C": "♣", "D": "♦", "S": "♠", "H": "♥"}


def pretty_card(code: str) -> str:
    rank, suit = code[0], code[1]
    return f"{'10' if rank == 'T' else rank}{SUIT_SYMBOLS[suit]}"
