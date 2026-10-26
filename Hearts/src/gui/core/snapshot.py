"""Immutable picture of the table, built from the public engine API only."""

from __future__ import annotations

from dataclasses import dataclass

from engine.game import HeartsGameEngine


@dataclass(frozen=True)
class TableSnapshot:
    """Everything the UI paints. Hands of *all* seats are included: the view decides
    what to reveal (hidden bot hands, hot-seat veil, all open when only bots play)."""

    deal_number: int
    num_players: int
    trick_number: int
    current_player: str | None
    hearts_broken: bool
    hands: dict[str, tuple[str, ...]]
    current_trick: tuple[tuple[str, str], ...]
    legal_moves: tuple[str, ...]  # for ``current_player`` only
    points: dict[str, int]  # raw penalty points so far (before Shooting the Moon)
    voids: dict[str, tuple[str, ...]]
    game_over: bool


def snapshot_from_engine(engine: HeartsGameEngine, deal_number: int) -> TableSnapshot:
    observations = {pid: engine.get_player_observation(pid) for pid in engine.player_ids}
    current = engine.current_player
    reference = observations[current] if current is not None else next(iter(observations.values()))
    return TableSnapshot(
        deal_number=deal_number,
        num_players=engine.num_players,
        trick_number=engine.trick_number,
        current_player=current,
        hearts_broken=engine.hearts_broken,
        hands={pid: tuple(obs.hand) for pid, obs in observations.items()},
        current_trick=tuple(reference.current_trick),
        legal_moves=tuple(observations[current].legal_moves) if current is not None else (),
        points=engine.points_taken,
        voids={pid: tuple(suits) for pid, suits in engine.exposed_voids.items()},
        game_over=engine.is_over,
    )
