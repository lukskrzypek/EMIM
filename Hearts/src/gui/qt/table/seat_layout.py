"""Table geometry for 3-4 players in scene units (pure maths, no Qt).

Seats are placed on an ellipse. Slot 0 is the bottom seat (the viewer); the next
players follow clockwise on screen: left, top, right.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Literal

SCENE_W = 1100.0
SCENE_H = 740.0
CENTER = (550.0, 340.0)
RX, RY = 430.0, 258.0

CARD_W = 70.0
CARD_H = 100.0

VIEWER_SCALE = 1.0
OTHER_SCALE = 0.72
TRICK_SCALE = 0.9
TRICK_SPREAD = 0.37  # trick slots sit this fraction of the way from the centre to the seat

# angle (degrees, clockwise from the bottom) of each slot
_ANGLES: dict[int, tuple[float, ...]] = {
    3: (0, 120, 240),
    4: (0, 90, 180, 270),
}


@dataclass(frozen=True)
class HandSpec:
    kind: Literal["row", "column"]
    cx: float  # centre of the fan
    cy: float
    scale: float
    max_span: float  # longest allowed extent along the fan direction
    plate: tuple[float, float]  # centre of the name plate


def seat_angles(num_players: int) -> tuple[float, ...]:
    return _ANGLES[num_players]


def seat_point(slot: int, num_players: int) -> tuple[float, float]:
    theta = math.radians(_ANGLES[num_players][slot])
    return CENTER[0] - RX * math.sin(theta), CENTER[1] + RY * math.cos(theta)


def slot_of(seat: str, viewer: str, player_ids: tuple[str, ...]) -> int:
    """Slot of ``seat`` when ``viewer`` sits at the bottom."""
    n = len(player_ids)
    return (player_ids.index(seat) - player_ids.index(viewer)) % n


def trick_slot_point(slot: int, num_players: int) -> tuple[float, float]:
    x, y = seat_point(slot, num_players)
    return (
        CENTER[0] + TRICK_SPREAD * (x - CENTER[0]),
        CENTER[1] + TRICK_SPREAD * (y - CENTER[1]),
    )


def hand_spec(slot: int, num_players: int) -> HandSpec:
    x, y = seat_point(slot, num_players)
    if slot == 0:
        return HandSpec("row", x, y + 6, VIEWER_SCALE, 720.0, (x, y + 88))
    if y < CENTER[1] - 40:  # upper seats: a row of smaller cards, plate above it
        height = CARD_H * OTHER_SCALE
        y += 14
        return HandSpec("row", x, y, OTHER_SCALE, 320.0,
                        (x, y - height / 2 - 22))
    # side seats: a column, plate above it
    return HandSpec("column", x, y + 10, OTHER_SCALE, 400.0, (x, y + 10 - 400.0 / 2 - 26))


def fan_positions(
    count: int, spec: HandSpec, *, face_up: bool
) -> list[tuple[float, float]]:
    """Card centres along the fan, evenly spread and centred on the spec."""
    if count == 0:
        return []
    card_len = (CARD_W if spec.kind == "row" else CARD_H) * spec.scale
    if spec.scale >= 1.0:
        natural = 36.0
    elif not face_up:
        natural = 11.0  # a fan of backs: only the count matters
    elif spec.kind == "row":
        natural = 28.0
    else:
        natural = 27.0
    step = natural
    if count > 1:
        step = min(natural, (spec.max_span - card_len) / (count - 1))
    span = step * (count - 1)
    start = -span / 2
    if spec.kind == "row":
        return [(spec.cx + start + i * step, spec.cy) for i in range(count)]
    return [(spec.cx, spec.cy + start + i * step) for i in range(count)]


def trick_card_point(slot: int, num_players: int, order: int) -> tuple[float, float]:
    """Cards of one trick keep their seat slot; ``order`` adds a tiny overlap offset."""
    x, y = trick_slot_point(slot, num_players)
    return x + order * 1.5, y + order * 1.5
