"""Lobby choices that survive a restart (JSON, tolerant of garbage and old versions)."""

from __future__ import annotations

import json
from dataclasses import dataclass, field

from gui.config import PLAYER_COUNTS, SMART_SAMPLES
from gui.core.seat_config import SeatConfig, SeatKind, clean_guidelines, clean_name

DEFAULT_PLAYERS = 4
MAX_DEALS = 1000


def default_seats(count: int = max(PLAYER_COUNTS)) -> tuple[SeatConfig, ...]:
    return tuple(
        SeatConfig(SeatKind.HUMAN if i == 0 else SeatKind.SMART) for i in range(count)
    )


@dataclass(frozen=True)
class LobbyState:
    players: int = DEFAULT_PLAYERS
    deals: int = 1
    seats: tuple[SeatConfig, ...] = field(default_factory=default_seats)  # always max(PLAYER_COUNTS)

    def to_json(self) -> str:
        return json.dumps(
            {
                "players": self.players,
                "deals": self.deals,
                "seats": [
                    {
                        "kind": seat.kind.value,
                        "groq_model": seat.groq_model,
                        "smart_samples": seat.smart_samples,
                        "groq_guidelines": seat.groq_guidelines,
                        "groq_name": seat.groq_name,
                    }
                    for seat in self.seats
                ],
            }
        )

    @classmethod
    def from_json(cls, text: str | None) -> LobbyState:
        """Parse what ``to_json`` wrote; anything unusable falls back to the default field."""
        default = cls()
        try:
            data = json.loads(text) if text else {}
        except (TypeError, ValueError):
            data = {}
        if not isinstance(data, dict):
            data = {}

        def number(key: str, fallback: int, low: int, high: int) -> int:
            value = data.get(key, fallback)
            if isinstance(value, bool) or not isinstance(value, int):
                return fallback
            return max(low, min(high, value))

        players = data.get("players")
        seats = list(default.seats)
        raw_seats = data.get("seats")
        if isinstance(raw_seats, list):
            for i, raw in enumerate(raw_seats[: len(seats)]):
                seats[i] = _parse_seat(raw, seats[i])
        return cls(
            players=players if players in PLAYER_COUNTS else default.players,
            deals=number("deals", default.deals, 1, MAX_DEALS),
            seats=tuple(seats),
        )


def _parse_seat(raw: object, fallback: SeatConfig) -> SeatConfig:
    if not isinstance(raw, dict):
        return fallback
    try:
        kind = SeatKind(raw.get("kind"))
    except ValueError:
        return fallback
    model = raw.get("groq_model")
    samples = raw.get("smart_samples")
    guidelines = raw.get("groq_guidelines")
    name = raw.get("groq_name")
    return SeatConfig(
        kind=kind,
        groq_model=model.strip() if isinstance(model, str) and model.strip() else fallback.groq_model,
        smart_samples=samples if isinstance(samples, int) and 0 <= samples <= 500 else SMART_SAMPLES,
        groq_guidelines=clean_guidelines(guidelines) if isinstance(guidelines, str) else "",
        groq_name=clean_name(name) if isinstance(name, str) else "",
    )
