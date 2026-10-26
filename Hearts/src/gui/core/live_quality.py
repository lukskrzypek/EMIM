"""Running quality statistics per seat, fed by ``LiveAnalysis``.

The bookkeeping mirrors ``evaluation.report.build_report`` move for move (same
``ModelQuality`` fields, same forced / illegal handling) so the live numbers and the
offline report of the same game agree; a test compares them on real logs.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass, field

from evaluation.evaluator import verdict_for
from evaluation.report import VERDICTS, ModelQuality
from gui.core.live_evaluator import LiveAnalysis


@dataclass(frozen=True)
class MoveRecord:
    """One judged move, kept for the sparkline and the history lists."""

    deal_number: int
    move_number: int
    card: str
    correctness: float
    verdict: str
    aggressiveness: float | None
    scenario: str
    regret: float
    best_card: str

    @property
    def forced(self) -> bool:
        return self.scenario == "only_move"


@dataclass
class SeatQuality:
    player_id: str
    label: str
    model: str = ""
    stats: ModelQuality = field(default_factory=lambda: ModelQuality(""))
    records: list[MoveRecord] = field(default_factory=list)
    regret_sum: float = 0.0
    best_picks: int = 0  # decisions where the chosen card was (one of) the best
    think_total: float = 0.0  # seconds the controller took, pauses excluded
    think_moves: int = 0
    think_max: float = 0.0

    @property
    def avg_think(self) -> float | None:
        """Mean response time in seconds (``None`` before the first timed move)."""
        return self.think_total / self.think_moves if self.think_moves else None

    @property
    def decisions(self) -> int:
        return self.stats.decisions

    @property
    def correctness(self) -> float | None:
        return self.stats.correctness

    @property
    def aggressiveness(self) -> float | None:
        return self.stats.aggressiveness

    @property
    def avg_regret(self) -> float | None:
        return self.regret_sum / self.decisions if self.decisions else None

    @property
    def best_rate(self) -> float | None:
        return self.best_picks / self.decisions if self.decisions else None

    def verdict_shares(self) -> dict[str, float]:
        """Share (0-1) of decisions per verdict, in ``VERDICTS`` order."""
        total = self.decisions
        return {v: (self.stats.verdicts[v] / total if total else 0.0) for v in VERDICTS}

    def scenario_means(self) -> dict[str, tuple[int, float]]:
        """scenario -> (moves, mean correctness)."""
        return {
            name: (len(values), sum(values) / len(values))
            for name, values in sorted(self.stats.scenarios.items())
        }

    def decision_records(self) -> list[MoveRecord]:
        return [r for r in self.records if not r.forced]


class LiveQuality:
    """Statistics of all seats of one session."""

    def __init__(self, labels: dict[str, str]) -> None:
        self.labels = dict(labels)
        self.seats: dict[str, SeatQuality] = {
            pid: SeatQuality(pid, label) for pid, label in labels.items()
        }
        self.last: LiveAnalysis | None = None
        self.last_move_number = 0
        self.last_by_player: dict[str, LiveAnalysis] = {}

    def seat(self, player_id: str) -> SeatQuality:
        return self.seats.setdefault(player_id, SeatQuality(player_id, player_id))

    def add_think(self, player_id: str, seconds: float) -> None:
        """Count one response time (call it for bots only; a human's time is not a response time)."""
        seat = self.seat(player_id)
        seat.think_total += seconds
        seat.think_moves += 1
        seat.think_max = max(seat.think_max, seconds)

    def record(self, analysis: LiveAnalysis, move_number: int = 0) -> MoveRecord | None:
        """Add one played move. ``None`` when the chosen card has no verdict (illegal)."""
        seat = self.seat(analysis.player_id)
        if analysis.model_name:
            seat.model = analysis.model_name
            seat.stats.model = analysis.model_name
        chosen = analysis.chosen_eval
        stats = seat.stats
        stats.moves += 1
        self.last, self.last_move_number = analysis, move_number
        self.last_by_player[analysis.player_id] = analysis
        if chosen is None:
            stats.illegal += 1
            return None

        regret = analysis.regret or 0.0
        record = MoveRecord(
            deal_number=analysis.deal_number,
            move_number=move_number,
            card=chosen.card,
            correctness=chosen.correctness,
            verdict=chosen.verdict,
            aggressiveness=chosen.aggressiveness,
            scenario=chosen.scenario,
            regret=regret,
            best_card=analysis.best.card,
        )
        seat.records.append(record)
        if chosen.forced:
            stats.forced += 1
            return record
        stats.correctness_sum += chosen.correctness
        stats.verdicts[verdict_for(chosen.correctness)] += 1
        stats.scenarios.setdefault(chosen.scenario, []).append(chosen.correctness)
        if chosen.aggressiveness is not None:
            stats.aggressiveness_sum += chosen.aggressiveness
            stats.aggressiveness_n += 1
        seat.regret_sum += regret
        seat.best_picks += regret <= 0.0
        return record

    @property
    def total_moves(self) -> int:
        return sum(s.stats.moves for s in self.seats.values())

    def by_model(self) -> dict[str, ModelQuality]:
        """Seats merged by controller name: the same grouping ``build_report`` uses."""
        return merge_by_model(self.seats.values())


def merge_by_model(seats: Iterable[SeatQuality]) -> dict[str, ModelQuality]:
    merged: dict[str, ModelQuality] = {}
    for seat in seats:
        if not seat.stats.moves:
            continue
        target = merged.setdefault(seat.model, ModelQuality(seat.model))
        s = seat.stats
        target.moves += s.moves
        target.forced += s.forced
        target.illegal += s.illegal
        target.correctness_sum += s.correctness_sum
        target.aggressiveness_sum += s.aggressiveness_sum
        target.aggressiveness_n += s.aggressiveness_n
        target.verdicts.update(Counter(s.verdicts))
        for name, values in s.scenarios.items():
            target.scenarios.setdefault(name, []).extend(values)
    return merged
