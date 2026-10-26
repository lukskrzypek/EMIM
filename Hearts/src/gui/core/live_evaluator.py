"""Live move quality: the user's ``evaluation`` package applied to the running game.

The state handed to the evaluator is built exactly like ``evaluation.trajectories``
rebuilds it from ``logs/trajectories.jsonl`` (hand before the move, finished tricks in
playing order, cards already on the table, legal moves from the engine), so a move gets
the same verdict live and in the offline report.

Cards are normalised at the boundary: the engine writes ``TH``, the evaluator ``10h``.
Everything leaving this module uses engine codes, so the UI never sees the other form.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass

from evaluation import GameState, InvalidState, RoundType, evaluate_all
from evaluation.params import Params
from evaluation.report import FORCED_SCENARIO
from gui.core.game_runner import AnalysisInput
from gui.core.table_model import TableModel

log = logging.getLogger(__name__)


def to_engine_code(card: str) -> str:
    """``10h`` / ``Th`` -> ``TH``."""
    rank, suit = card[:-1].upper(), card[-1].upper()
    return f"{'T' if rank == '10' else rank}{suit}"


@dataclass(frozen=True)
class MoveEval:
    """One legal card as judged by the evaluator (engine card code)."""

    card: str
    correctness: float  # 0-100
    verdict: str
    aggressiveness: float | None  # None for forced moves
    aggressiveness_label: str
    scenario: str
    reasons: tuple[str, ...] = ()

    @property
    def forced(self) -> bool:
        return self.scenario == FORCED_SCENARIO


@dataclass(frozen=True)
class LiveAnalysis:
    """All legal alternatives of one position, best first, and the card that was played."""

    player_id: str
    deal_number: int
    ranking: tuple[MoveEval, ...]
    chosen: str | None  # None for a hint (nothing played yet)
    model_name: str = ""

    @property
    def chosen_eval(self) -> MoveEval | None:
        return next((m for m in self.ranking if m.card == self.chosen), None)

    @property
    def best(self) -> MoveEval:
        return self.ranking[0]

    @property
    def regret(self) -> float | None:
        """Correctness lost against the best alternative (0 = played the best card)."""
        chosen = self.chosen_eval
        return None if chosen is None else round(self.best.correctness - chosen.correctness, 1)

    @property
    def rank(self) -> int | None:
        """1 = best; equal scores share a place."""
        chosen = self.chosen_eval
        if chosen is None:
            return None
        return 1 + sum(m.correctness > chosen.correctness for m in self.ranking)


def evaluate_position(
    *,
    player_id: str,
    deal_number: int,
    hand: Sequence[str],
    history: Sequence[Sequence[str]],
    current_trick: Sequence[str],
    num_players: int,
    legal_moves: Sequence[str],
    chosen: str | None = None,
    model_name: str = "",
    params: Params | None = None,
) -> LiveAnalysis | None:
    """Rate every legal card; ``None`` when the position is rejected by the evaluator."""
    state = GameState(
        hand=list(hand),
        round_type=RoundType.HEARTS,
        history=[list(t) for t in history],
        current_trick=list(current_trick),
        num_players=num_players,
        legal_moves=list(legal_moves),
    )
    try:
        evaluations = evaluate_all(state, params)
    except InvalidState as exc:
        log.warning("Live evaluation rejected the position: %s", exc)
        return None
    ranking = tuple(
        MoveEval(
            card=to_engine_code(e.card),
            correctness=e.correctness,  # type: ignore[arg-type]  # legal cards always have one
            verdict=e.verdict or "",
            aggressiveness=e.aggressiveness,
            aggressiveness_label=e.aggressiveness_label or "",
            scenario=e.scenario or "?",
            reasons=tuple(e.reasons),
        )
        for e in evaluations
        if e.legal
    )
    if not ranking:
        return None
    return LiveAnalysis(player_id, deal_number, ranking, chosen, model_name)


def hint_for_table(
    model: TableModel, player_id: str, params: Params | None = None
) -> LiveAnalysis | None:
    """Rating of the position ``player_id`` is about to move in (a hint for a human).

    Uses only what that player sees: own hand, table, finished tricks."""
    snap = model.snapshot
    if snap is None or snap.current_player != player_id or not snap.legal_moves:
        return None
    return evaluate_position(
        player_id=player_id,
        deal_number=snap.deal_number,
        hand=snap.hands[player_id],
        history=model.tricks,
        current_trick=[card for _, card in snap.current_trick],
        num_players=snap.num_players,
        legal_moves=snap.legal_moves,
        params=params,
    )


class LiveEvaluator:
    """``GameRunner`` analyzer hook. Runs on the runner thread; can be switched off live."""

    def __init__(self, params: Params | None = None) -> None:
        self.params = params
        self.enabled = True

    def __call__(self, data: AnalysisInput) -> LiveAnalysis | None:
        if not self.enabled:
            return None
        observation = data.observation
        return evaluate_position(
            player_id=observation.player_id,
            deal_number=data.deal_number,
            hand=observation.hand,
            history=data.history,
            current_trick=[card for _, card in observation.current_trick],
            num_players=observation.num_players,
            legal_moves=observation.legal_moves,
            chosen=data.chosen,
            model_name=data.model_name,
            params=self.params,
        )
