"""Publiczne API: ocena posunięć w kierkach (poprawność + agresywność).

    from evaluation import GameState, RoundType, evaluate_move, evaluate_all

Port biblioteki "kierki" (system oceny) dostosowany do silnika Hearts: 2-5 graczy,
runda RoundType.HEARTS (kier = 1 pkt, dama pik = 13 pkt) i legalne ruchy z silnika.
Zasady działania i parametry: evaluation/strategy.py, evaluation/params.py.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .cards import parse_card
from .context import GameState, InvalidState, prepare
from .params import Params
from .strategy import score_move

__all__ = ["GameState", "InvalidState", "MoveEvaluation", "evaluate_all", "evaluate_move"]


@dataclass
class MoveEvaluation:
    card: str
    legal: bool
    errors: list[str]
    correctness: float | None = None          # 0-100
    verdict: str | None = None                # optymalne / poprawne / wątpliwe / niepoprawne
    aggressiveness: float | None = None       # 0-100; None = nie dotyczy (ruch wymuszony)
    aggressiveness_label: str | None = None
    scenario: str | None = None
    reasons: list[str] = field(default_factory=list)
    components: dict[str, float] = field(default_factory=dict)


def verdict_for(correctness: float) -> str:
    if correctness >= 90:
        return "optymalne"
    if correctness >= 70:
        return "poprawne"
    if correctness >= 40:
        return "wątpliwe"
    return "niepoprawne"


def aggressiveness_label_for(score: float | None) -> str:
    if score is None:
        return "neutralne (wymuszone)"
    if score < 15:
        return "bardzo defensywny"
    if score < 35:
        return "defensywny"
    if score < 55:
        return "wyważony"
    if score < 75:
        return "agresywny"
    return "bardzo agresywny"


def evaluate_move(state: GameState, card: str, params: Params | None = None) -> MoveEvaluation:
    ctx = prepare(state, params or Params())
    try:
        c = parse_card(card)
    except ValueError as e:
        return MoveEvaluation(card, False, [str(e)])

    if c not in ctx.hand:
        return MoveEvaluation(str(c), False, [f"Karty {c} nie ma na ręce gracza."])
    if c not in ctx.legal_cards():
        if state.legal_moves is not None:
            return MoveEvaluation(str(c), False, [f"Karta {c} nie jest legalnym ruchem w tej sytuacji."])
        return MoveEvaluation(
            str(c), False, [f"Trzeba dołożyć do koloru '{ctx.lead_suit}' - gracz ma taką kartę."])

    sc = score_move(ctx, c)
    corr = round(sc.correctness, 1)
    aggr = None if sc.aggressiveness is None else round(sc.aggressiveness, 1)
    return MoveEvaluation(
        card=str(c), legal=True, errors=[],
        correctness=corr, verdict=verdict_for(corr),
        aggressiveness=aggr, aggressiveness_label=aggressiveness_label_for(aggr),
        scenario=sc.scenario, reasons=sc.reasons,
        components={k: round(v, 3) for k, v in sc.components.items()},
    )


def evaluate_all(state: GameState, params: Params | None = None) -> list[MoveEvaluation]:
    """Oceny wszystkich legalnych ruchów: od najlepszego (poprawność), przy remisie od najmniej agresywnego."""
    p = params or Params()
    ctx = prepare(state, p)
    res = [evaluate_move(state, str(c), p) for c in ctx.legal_cards()]
    return sorted(res, key=lambda e: (-e.correctness, e.aggressiveness or 0.0))
