"""Append-only JSONL log of prompts and chosen moves."""

from __future__ import annotations

import json
from pathlib import Path

from engine.game import PlayerObservation

DEFAULT_LOG_PATH = Path("logs") / "trajectories.jsonl"


class ICLLogger:
    """Writes one JSON line per move to ``logs/trajectories.jsonl``.

    ``model`` names who played the move: an LLM id, ``human`` or ``smart_bot``.
    """

    def __init__(self, path: str | Path = DEFAULT_LOG_PATH) -> None:
        self.path = Path(path)

    def log(
        self,
        observation: PlayerObservation,
        chosen_move: str,
        reasoning: str = "",
        model: str = "unknown",
    ) -> None:
        record = {
            "player_id": observation.player_id,
            "model": model,
            "prompt_context": observation.to_icl_prompt(),
            "legal_moves": list(observation.legal_moves),
            "chosen_move": chosen_move,
            "reasoning": reasoning,
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
