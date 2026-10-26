"""Messages sent from the runner thread to the UI. All are immutable."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from engine.game import PlayResult
from gui.core.snapshot import TableSnapshot


@dataclass(frozen=True)
class SessionStarted:
    player_ids: tuple[str, ...]
    seat_labels: dict[str, str]  # P0 -> "Człowiek" / "SmartHeartsBot" / model id
    total_deals: int


@dataclass(frozen=True)
class DealStarted:
    deal_number: int
    total_deals: int
    snapshot: TableSnapshot


@dataclass(frozen=True)
class TurnStarted:
    """``player_id`` is about to choose (a bot starts thinking, a human may click)."""

    player_id: str
    is_human: bool
    snapshot: TableSnapshot


@dataclass(frozen=True)
class MovePlayed:
    deal_number: int
    move_number: int  # 1-based within the deal
    player_id: str
    card: str
    model_name: str
    think_seconds: float
    reasoning: str
    result: PlayResult
    snapshot: TableSnapshot  # state after the move
    analysis: Any | None = None  # filled by an optional analyzer hook (quality system)


@dataclass(frozen=True)
class TrickCompleted:
    deal_number: int
    trick_number: int
    cards: tuple[tuple[str, str], ...]
    winner: str
    points: int
    snapshot: TableSnapshot


@dataclass(frozen=True)
class DealFinished:
    deal_number: int
    scores: dict[str, int]
    shot_the_moon: str | None
    totals: dict[str, int]
    wins: dict[str, int]
    ties: int


@dataclass(frozen=True)
class SessionFinished:
    totals: dict[str, int]
    wins: dict[str, int]
    ties: int
    deals_played: int
    winners: tuple[str, ...]
    aborted: bool


@dataclass(frozen=True)
class PauseChanged:
    paused: bool


@dataclass(frozen=True)
class ControllerError:
    """A seat failed; the runner waits for ``GameRunner.resolve_error``."""

    player_id: str
    seat_label: str
    message: str


@dataclass(frozen=True)
class Notice:
    text: str


@dataclass(frozen=True)
class BotUnavailable:
    """A Groq seat cannot play on (``reason``: ``"tokens"`` or ``"access"``); the game ends."""

    player_id: str
    seat_label: str
    reason: str
    message: str


@dataclass(frozen=True)
class FatalError:
    message: str


GameEvent = (
    SessionStarted
    | DealStarted
    | TurnStarted
    | MovePlayed
    | TrickCompleted
    | DealFinished
    | SessionFinished
    | PauseChanged
    | ControllerError
    | Notice
    | BotUnavailable
    | FatalError
)
