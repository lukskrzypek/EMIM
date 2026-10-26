"""Lobby output: who sits where and how many deals are played."""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from controllers.groq_icl_bot import DEFAULT_MODEL
from gui.config import GUIDELINES_MAX_CHARS, LOG_PATH, NAME_MAX_CHARS, PLAYER_COUNTS, SMART_SAMPLES


class SeatKind(str, Enum):
    HUMAN = "human"
    SMART = "smart"
    GROQ = "groq"


SEAT_LABELS: dict[SeatKind, str] = {
    SeatKind.HUMAN: "Człowiek",
    SeatKind.SMART: "SmartHeartsBot",
    SeatKind.GROQ: "GroqICLBot",
}


@dataclass(frozen=True)
class SeatConfig:
    kind: SeatKind
    groq_model: str = DEFAULT_MODEL
    smart_samples: int = SMART_SAMPLES
    groq_guidelines: str = ""  # extra system-prompt line (<= GUIDELINES_MAX_CHARS); "" = bot default
    groq_name: str = ""  # tells two seats of one model apart (<= NAME_MAX_CHARS); "" = no suffix

    @property
    def label(self) -> str:
        return SEAT_LABELS[self.kind]

    @property
    def display_name(self) -> str:
        """What the panels call the seat: the model (with its name) for Groq, else the kind."""
        if self.kind is SeatKind.GROQ:
            return f"{self.groq_model} ({self.groq_name})" if self.groq_name else self.groq_model
        return self.label

    @property
    def memory_key(self) -> str:
        """Model id the memory file is named after: ``<model>`` or ``<model>_<name>``."""
        return f"{self.groq_model}_{self.groq_name}" if self.groq_name else self.groq_model


def clean_guidelines(text: str) -> str:
    """One line, trimmed, at most ``GUIDELINES_MAX_CHARS`` characters."""
    return " ".join(text.split())[:GUIDELINES_MAX_CHARS].strip()


def clean_name(text: str) -> str:
    """A seat name that is safe inside a file name: letters, digits, ``-``, ``_``; short."""
    return re.sub(r"[^\w-]", "_", text.strip())[:NAME_MAX_CHARS]


def _memory_id(seat: SeatConfig) -> str:
    return seat.memory_key.strip().casefold()  # Windows file names ignore the case


def duplicate_groq_memories(seats: Sequence[SeatConfig]) -> list[str]:
    """Groq seats that would share one memory file (same model and same name)."""
    first: dict[str, str] = {}
    count: Counter[str] = Counter()
    for seat in seats:
        if seat.kind is SeatKind.GROQ:
            key = _memory_id(seat)
            first.setdefault(key, seat.display_name)
            count[key] += 1
    return [first[key] for key, n in count.items() if n > 1]


@dataclass(frozen=True)
class SessionConfig:
    """Everything the runner needs; seats are ``P0``, ``P1``, ... in order."""

    seats: tuple[SeatConfig, ...]
    deals: int = 1
    seed: int | None = None  # deal ``k`` (0-based) is dealt with ``seed + k``
    log_path: Path | None = LOG_PATH  # trajectories.jsonl; ``None`` switches logging off

    def __post_init__(self) -> None:
        if len(self.seats) not in PLAYER_COUNTS:
            raise ValueError(f"Player count must be one of {PLAYER_COUNTS}, got {len(self.seats)}")
        if self.deals < 1:
            raise ValueError(f"Deal count must be positive, got {self.deals}")
        if duplicates := duplicate_groq_memories(self.seats):
            # Two seats on one memory file would overwrite each other's notes.
            raise ValueError(
                f"Seats of one Groq model need different names, shared memory: {', '.join(duplicates)}"
            )

    @property
    def num_players(self) -> int:
        return len(self.seats)

    @property
    def player_ids(self) -> tuple[str, ...]:
        return tuple(f"P{i}" for i in range(self.num_players))

    @property
    def has_human(self) -> bool:
        return any(seat.kind is SeatKind.HUMAN for seat in self.seats)

    @property
    def human_ids(self) -> tuple[str, ...]:
        return tuple(
            pid for pid, seat in zip(self.player_ids, self.seats, strict=True)
            if seat.kind is SeatKind.HUMAN
        )
