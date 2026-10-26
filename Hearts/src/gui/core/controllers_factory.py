"""Builds a controller for each seat of a ``SessionConfig``."""

from __future__ import annotations

import importlib.util
from pathlib import Path

from controllers.base import PlayerController
from controllers.ai_bot import AIBot, get_provider, read_api_key
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
    if seat.kind is SeatKind.AI:
        return AIBot(
            player_id,
            model=seat.ai_model,
            provider=seat.ai_provider,
            trajectories_path=trajectories_path,  # few-shot stays off: num_examples defaults to 0
            name=seat.ai_name,  # -> model_name, memory file ..._<name>.txt and the bot's logs
            # empty -> None keeps the bot's own default (USER_GUIDELINES in ai_bot.py)
            guidelines=clean_guidelines(seat.ai_guidelines) or None,
        )
    raise ValueError(f"Unknown seat kind: {seat.kind!r}")


def availability_problem(seat: SeatConfig, api_key_path: Path | None = None) -> str | None:
    """Why this seat could not play (missing SDK or key), or ``None`` when it is ready.

    ``api_key_path`` overrides the key file of the seat's provider.
    """
    if seat.kind is not SeatKind.AI:
        return None
    provider = get_provider(seat.ai_provider)
    if importlib.util.find_spec(provider.package) is None:
        return f"Brak pakietu '{provider.package}' (pip install {provider.package})."
    try:
        read_api_key(api_key_path or provider.key_path, provider.id)
    except RuntimeError as exc:
        return str(exc)
    return None
