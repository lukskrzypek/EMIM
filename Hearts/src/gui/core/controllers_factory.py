"""Builds a controller for each seat of a ``SessionConfig``."""

from __future__ import annotations

import importlib.util
from pathlib import Path

from controllers.base import PlayerController
from controllers.groq_icl_bot import DEFAULT_API_KEY_PATH, GroqICLBot, read_api_key
from controllers.smart_bot import SmartHeartsBot
from gui.config import LOG_PATH
from gui.core.human_controller import HumanGuiController
from gui.core.seat_config import SeatConfig, SeatKind, clean_guidelines


def build_controller(
    seat: SeatConfig,
    player_id: str,
    index: int,
    *,
    trajectories_path: Path | None = LOG_PATH,
) -> PlayerController:
    """Same construction as ``main._make_controller`` (``SmartHeartsBot`` seed = seat index)."""
    if seat.kind is SeatKind.HUMAN:
        return HumanGuiController()
    if seat.kind is SeatKind.SMART:
        return SmartHeartsBot(num_samples=seat.smart_samples, seed=index)
    if seat.kind is SeatKind.GROQ:
        return GroqICLBot(
            player_id,
            model=seat.groq_model,
            trajectories_path=trajectories_path,  # few-shot stays off: num_examples defaults to 0
            name=seat.groq_name,  # -> model_name, memory file ..._<name>.txt and the bot's logs
            # empty -> None keeps the bot's own default (USER_GUIDELINES in groq_icl_bot.py)
            guidelines=clean_guidelines(seat.groq_guidelines) or None,
        )
    raise ValueError(f"Unknown seat kind: {seat.kind!r}")


def availability_problem(seat: SeatConfig, api_key_path: Path = DEFAULT_API_KEY_PATH) -> str | None:
    """Why this seat could not play (missing SDK or key), or ``None`` when it is ready."""
    if seat.kind is not SeatKind.GROQ:
        return None
    if importlib.util.find_spec("groq") is None:
        return "Brak pakietu 'groq' (pip install groq)."
    try:
        read_api_key(api_key_path)
    except RuntimeError as exc:
        return str(exc)
    return None
