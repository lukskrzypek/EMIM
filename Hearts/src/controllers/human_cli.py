"""Hotseat controller: one keyboard, hands hidden between turns."""

from __future__ import annotations

import os

from controllers.base import PlayerController
from engine.game import PlayerObservation


def _separate_players() -> None:
    """Clear the terminal so the next player does not see the previous hand."""
    os.system("cls" if os.name == "nt" else "clear")
    print("=" * 64)


def _parse_choice(raw: str, legal_moves: list[str]) -> str | None:
    compact = raw.replace(" ", "").upper()
    if not compact:
        return None
    if compact.isdigit():
        index = int(compact)
        if 0 <= index < len(legal_moves):
            return legal_moves[index]
        return None
    if compact in legal_moves:
        return compact
    return None


class HumanCLIController(PlayerController):
    """Shows ``to_icl_prompt()`` and reads a card index or code (``0`` or ``2C``)."""

    def select_move(self, observation: PlayerObservation) -> str:
        if not observation.legal_moves:
            raise ValueError(f"{observation.player_id} has no legal moves")

        _separate_players()
        input(f"{observation.player_id}, naciśnij Enter, aby zobaczyć karty. ")
        _separate_players()
        print(observation.to_icl_prompt())
        print()
        for index, card in enumerate(observation.legal_moves):
            print(f"  [{index}] {card}")
        print()

        while True:
            raw = input("Wybierz kartę (indeks lub nazwa, np. 0 lub 2C): ")
            chosen = _parse_choice(raw, observation.legal_moves)
            if chosen is not None:
                return chosen
            print("Nieprawidłowy wybór. Podaj indeks albo kod karty z listy.")
