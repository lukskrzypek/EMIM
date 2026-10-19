"""Controller interface for choosing a legal card."""

from __future__ import annotations

from abc import ABC, abstractmethod

from engine.game import PlayerObservation


class PlayerController(ABC):
    """Chooses one legal card from a player's observation."""

    last_reasoning: str = ""

    @abstractmethod
    def select_move(self, observation: PlayerObservation) -> str:
        """Return a card code that belongs to ``observation.legal_moves``."""
