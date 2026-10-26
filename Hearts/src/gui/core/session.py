"""Running totals over several deals (GUI counterpart of ``main.play_session`` bookkeeping)."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field


def leaders(scores: Mapping[str, int]) -> list[str]:
    """Players with the lowest score (lower is better in Hearts)."""
    best = min(scores.values())
    return [pid for pid, pts in scores.items() if pts == best]


@dataclass
class SessionStats:
    player_ids: Sequence[str]
    totals: dict[str, int] = field(init=False)
    wins: dict[str, int] = field(init=False)
    ties: int = 0
    deals_played: int = 0

    def __post_init__(self) -> None:
        self.totals = dict.fromkeys(self.player_ids, 0)
        self.wins = dict.fromkeys(self.player_ids, 0)

    def record(self, scores: Mapping[str, int]) -> None:
        """Add one finished deal (scores already include shooting the moon)."""
        for pid, pts in scores.items():
            self.totals[pid] += pts
        winners = leaders(scores)
        if len(winners) == 1:
            self.wins[winners[0]] += 1
        else:
            self.ties += 1
        self.deals_played += 1

    @property
    def leaders(self) -> list[str]:
        return leaders(self.totals)

    @property
    def averages(self) -> dict[str, float]:
        if not self.deals_played:
            return dict.fromkeys(self.player_ids, 0.0)
        return {pid: pts / self.deals_played for pid, pts in self.totals.items()}
