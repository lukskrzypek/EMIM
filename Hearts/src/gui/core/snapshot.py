"""Immutable picture of the table, built from the public engine API only."""

from __future__ import annotations

from dataclasses import dataclass

from engine.contracts import GameContract
from engine.state import GameState


@dataclass(frozen=True)
class TableSnapshot:
    """Everything the UI paints. Hands of *all* seats are included: the view decides
    what to reveal (hidden bot hands, hot-seat veil, all open when only bots play)."""

    deal_number: int
    total_deals: int
    num_players: int
    trick_number: int
    total_tricks: int
    contract: GameContract
    declarer: str
    current_player: str | None
    hands: dict[str, tuple[str, ...]]
    current_trick: tuple[tuple[str, str], ...]
    legal_moves: tuple[str, ...]  # for ``current_player`` only
    points: dict[str, int]  # penalties taken in this deal so far
    total_points: dict[str, int]  # penalties of the whole match (finished deals)
    voids: dict[str, tuple[str, ...]]
    deal_over: bool  # every trick of this deal is played


def snapshot_from_engine(engine: GameState, deal_number: int | None = None) -> TableSnapshot:
    observations = {pid: engine.get_player_observation(pid) for pid in engine.player_ids}
    current = engine.current_player
    reference = observations[current] if current is not None else next(iter(observations.values()))
    return TableSnapshot(
        deal_number=engine.deal_number if deal_number is None else deal_number,
        total_deals=engine.total_deals,
        num_players=engine.num_players,
        trick_number=engine.trick_number,
        total_tricks=engine.total_tricks,
        contract=engine.current_contract,
        declarer=engine.declarer,
        current_player=current,
        hands={pid: tuple(obs.hand) for pid, obs in observations.items()},
        current_trick=tuple(reference.current_trick),
        legal_moves=tuple(observations[current].legal_moves) if current is not None else (),
        points=dict(engine.scores),
        total_points=dict(engine.total_scores),
        voids={pid: tuple(suits) for pid, suits in engine.exposed_voids.items()},
        deal_over=engine.deal_finished or engine.is_over,
    )
