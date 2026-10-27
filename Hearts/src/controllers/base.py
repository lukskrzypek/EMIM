"""Controller interface for choosing a legal card."""

from __future__ import annotations

from abc import ABC, abstractmethod

from engine.observation import PlayerObservation


class PlayerController(ABC):
    """Chooses one legal card from a player's observation."""

    last_reasoning: str = ""
    # Saved with every logged move so the quality report can group by who played it.
    model_name: str = "unknown"

    @abstractmethod
    def select_move(self, observation: PlayerObservation) -> str:
        """Return a card code that belongs to ``observation.legal_moves``."""
