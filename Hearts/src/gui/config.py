"""Constants shared by the GUI (mirrors the ones at the top of ``main.py``)."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
LOG_PATH = ROOT / "logs" / "trajectories.jsonl"
CARDS_DIR = ROOT / "assets" / "cards"  # optional PNG deck: 2C.png ... AS.png, back.png

PLAYER_COUNTS: tuple[int, ...] = (3, 4)  # King: 3 or 4 players
MAX_GAMES = 100  # lobby: how many games of 7 deals to play
SMART_SAMPLES = 40
GUIDELINES_MAX_CHARS = 100  # user's extra instructions for an AI bot
NAME_MAX_CHARS = 10  # seat name that separates the memory files of one model
# Players left out of the offline quality report (same default as main.py).
IGNORED_PLAYERS: tuple[str, ...] = ("human", "smart_bot")

DEFAULT_DELAY_S = 1.0  # pause between two bot moves
MAX_DELAY_S = 3.0
