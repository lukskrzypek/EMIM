"""What the bots said and how long they took (Qt-free model behind the "Bot" tab)."""

from __future__ import annotations

from collections import deque
from collections.abc import Sequence
from dataclasses import dataclass, field

from controllers.groq_icl_bot import DEFAULT_MEMORY_DIR, memory_filename
from gui.core.events import GameEvent, MovePlayed, SessionStarted, TurnStarted
from gui.core.live_evaluator import LiveAnalysis

MAX_ENTRIES = 40
MEMORY_TAIL_CHARS = 4000


@dataclass(frozen=True)
class InsightEntry:
    deal_number: int
    move_number: int
    card: str
    think_seconds: float
    reasoning: str
    verdict: str | None = None
    correctness: float | None = None


@dataclass
class SeatInsight:
    player_id: str
    label: str
    model: str = ""
    entries: deque[InsightEntry] = field(default_factory=lambda: deque(maxlen=MAX_ENTRIES))
    moves: int = 0
    think_total: float = 0.0
    think_max: float = 0.0

    @property
    def avg_think(self) -> float | None:
        return self.think_total / self.moves if self.moves else None


def read_groq_memory(model: str) -> str:
    """Tail of a Groq bot's scratchpad file (``logs/memory_<model>.txt``) or a placeholder."""
    path = DEFAULT_MEMORY_DIR / memory_filename(model)
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return "(brak pliku pamięci)"
    if not text.strip():
        return "(pusta)"
    return text[-MEMORY_TAIL_CHARS:]


class InsightModel:
    def __init__(self, labels: dict[str, str], human_ids: Sequence[str]) -> None:
        self.human_ids = tuple(human_ids)
        self._reset(labels)

    def _reset(self, labels: dict[str, str]) -> None:
        self.seats: dict[str, SeatInsight] = {
            pid: SeatInsight(pid, label) for pid, label in labels.items() if pid not in self.human_ids
        }
        self.last_player: str | None = None
        self.thinking: str | None = None

    def apply(self, event: GameEvent) -> None:
        if isinstance(event, SessionStarted):
            self._reset(event.seat_labels)
        elif isinstance(event, TurnStarted):
            self.thinking = None if event.is_human else event.player_id
        elif isinstance(event, MovePlayed):
            self.thinking = None
            seat = self.seats.get(event.player_id)
            if seat is None:
                return
            analysis = event.analysis if isinstance(event.analysis, LiveAnalysis) else None
            chosen = analysis.chosen_eval if analysis else None
            seat.model = event.model_name
            seat.moves += 1
            seat.think_total += event.think_seconds
            seat.think_max = max(seat.think_max, event.think_seconds)
            seat.entries.append(
                InsightEntry(
                    event.deal_number,
                    event.move_number,
                    event.card,
                    event.think_seconds,
                    event.reasoning,
                    chosen.verdict if chosen else None,
                    chosen.correctness if chosen else None,
                )
            )
            self.last_player = event.player_id
