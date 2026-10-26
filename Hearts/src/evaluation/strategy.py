"""Reguły oceny posunięć (poprawność 0-100 i agresywność 0-100) - patrz README, sekcja "Reguły".

Scenariusze (wybierane w score_move):
  only_move    - jedyna legalna karta
  forced_take  - każda moja legalna karta na pewno bierze lewę
  lead         - ja otwieram lewę
  follow_take  - dokładam do koloru kartą, która bije aktualną
  follow_duck  - dokładam do koloru kartą, która nie bije (nie wezmę lewy)
  void_discard - nie mam koloru, zrzucam dowolną kartę (też nie wezmę lewy)
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field

from .cards import Card
from .context import Ctx


@dataclass
class Score:
    scenario: str
    correctness: float
    aggressiveness: float | None          # None = nie dotyczy (ruch wymuszony)
    reasons: list[str] = field(default_factory=list)
    components: dict[str, float] = field(default_factory=dict)


def _clamp(x: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, x))


def _rank_frac(card: Card) -> float:
    """0 dla dwójki, 1 dla asa."""
    return (card.value - 2) / 12


def score_move(ctx: Ctx, card: Card) -> Score:
    legal = ctx.legal_cards()
    if len(legal) == 1:
        return Score("only_move", 100.0, None, ["Jedyna legalna karta - ruch wymuszony."])
    if all(ctx.sure_win(c) for c in legal):
        return _forced_take(ctx, card, legal)
    if not ctx.current:
        return _lead(ctx, card)
    if not ctx.beats_current(card):
        return _safe_discard(ctx, card, legal)
    return _follow_take(ctx, card, legal)


# ---------------------------------------------------------------------------
def _forced_take(ctx: Ctx, card: Card, legal: list[Card]) -> Score:
    """Każda legalna karta na pewno bierze lewę: najlepiej najwyższa niepunktowana."""
    P = ctx.params
    reasons = [("Każda moja legalna karta na pewno bierze lewę - zebranie jest wymuszone, "
                "więc agresywności nie oceniam.")]
    nonpen = sorted((c for c in legal if ctx.pen(c) == 0), key=lambda c: -c.value)
    if nonpen and ctx.pen(card) > 0:
        ref = ctx.ref_penalty
        corr = P.forced_penalty_card_cap * (1 - min(1.0, ctx.pen(card) / ref)) if ref > 0 else 0.0
        reasons.append("Biorę lewę kartą punktowaną, choć mam niepunktowane.")
    elif nonpen:
        k = nonpen.index(card)
        corr = 100 - P.forced_rank_loss * k / max(1, len(nonpen) - 1)
        reasons.append("Najwyższa niepunktowana karta - optymalnie." if k == 0
                       else "Są wyższe niepunktowane karty, którymi lepiej zebrać lewę.")
    else:
        order = sorted(legal, key=lambda c: (ctx.pen(c), -c.value))
        k = order.index(card)
        corr = 100 - P.forced_rank_loss * k / max(1, len(order) - 1)
        reasons.append("Wszystkie karty są punktowane - najlepsza najmniejsza kara, "
                       "a przy równych najwyższa karta." if k == 0
                       else "Są lepsze karty do wymuszonego zebrania (mniejsza kara lub wyższa karta).")
    return Score("forced_take", _clamp(corr), None, reasons)


# ---------------------------------------------------------------------------
def _intent(ctx: Ctx, p_win: float) -> float:
    """Zamiar zebrania lewy: rośnie z numerem lewy (po wygranej trzeba wyjść w następnej)."""
    P = ctx.params
    return p_win * (P.take_aggr_base + P.take_aggr_progress * ctx.progress)


def _follow_take(ctx: Ctx, card: Card, legal: list[Card]) -> Score:
    """Dokładam kartą, która bije aktualną, choć nie jestem do tego zmuszony."""
    P = ctx.params
    p, risk = ctx.p_win(card), ctx.risk(card)
    known = (ctx.rules.trick_penalty(ctx.trick_number)
             + sum(ctx.pen(c) for c in ctx.current) + ctx.pen(card))
    corr = 100.0 * (1 - risk)
    reasons = []
    if known == 0:
        best = max(c.value for c in legal if ctx.pen(c) == 0)
        corr -= P.take_not_highest_loss * (best - card.value) / 12
        reasons.append("Celowe zebranie lewy bez kar - agresywne, rośnie z numerem lewy."
                       + (" Najwyższa niepunktowana karta." if card.value == best
                          else " Lepiej zebrać wyższą niepunktowaną kartą."))
    else:
        reasons.append("Zbieram lewę z karami (na stole lub z karą za lewę), choć mogłem jej uniknąć.")
        if any(not ctx.beats_current(c) for c in legal):
            # znane kary biorę świadomie - mogłem dołożyć kartę, która nie bierze
            corr = min(corr, 100 - p * (100 - P.take_known_penalty_cap))
    if risk >= 0.5:
        reasons.append(f"Wysokie ryzyko wzięcia kar (ryzyko={risk:.2f}).")
    void = ctx.void_prob(card.suit)
    aggr = _intent(ctx, p) + P.void_aggr * void * p + P.risk_aggr * risk
    return Score("follow_take", _clamp(corr), _clamp(aggr), reasons,
                 {"p_win": p, "risk": risk, "void_prob": void, "progress": ctx.progress})


# ---------------------------------------------------------------------------
def _safe_discard(ctx: Ctx, card: Card, legal: list[Card]) -> Score:
    """Karta, która na pewno nie weźmie lewy (zrzut przy braku koloru albo przebita)."""
    P = ctx.params
    safe = [c for c in legal if not ctx.beats_current(c)]
    pens = [c for c in safe if ctx.pen(c) > 0]
    max_pen = max((ctx.pen(c) for c in pens), default=0)
    ref = ctx.ref_penalty
    r = _rank_frac(card)
    scenario = "void_discard" if card.suit != ctx.lead_suit else "follow_duck"
    comps: dict[str, float] = {}
    reasons = []
    if ctx.pen(card) > 0:
        corr = 100 - P.dump_order_loss * (1 - ctx.pen(card) / max_pen) - P.dump_rank_loss * (1 - r)
        aggr = P.dump_pen_aggr
        reasons.append("Pozbywam się karty punktowanej na lewę, której nie wezmę - bardzo poprawne.")
        if ctx.pen(card) < max_pen:
            reasons.append("Mogłem zrzucić większą karę.")
    else:
        missed = P.missed_dump_loss * min(1.0, max_pen / ref) if pens and ref > 0 else 0.0
        top = max(c.value for c in safe if ctx.pen(c) == 0)
        corr = 100 - missed - P.shed_rank_loss * (top - card.value) / 12
        holds_pen = any(ctx.pen(c) > 0 for c in ctx.hand)
        heavy = ctx.heavy_prob(card.suit) if holds_pen else 0.0
        corr += P.suspect_bonus * heavy
        kept = min(1.0, sum(ctx.pen(c) for c in pens) / ref) if pens and ref > 0 else 0.0
        aggr = P.shed_base_aggr + P.shed_high_aggr * r + P.shed_kept_aggr * kept
        comps = {"heavy_prob": heavy, "kept_penalty": kept}
        if scenario == "follow_duck":
            take = _safe_take_value(ctx, legal)
            corr -= P.duck_missed_take_loss * take
            comps["missed_take"] = take
            if take >= 0.3:
                reasons.append("Mogłem bezpiecznie zebrać czystą lewę - szkoda niskiej karty na tym etapie.")
        if card.value < top:
            reasons.append("Mam wyższą kartę, która też nie bierze lewy.")
        if pens:
            reasons.append("Zrzucam kartę niepunktowaną, choć mogłem zrzucić punktową - "
                           "bardziej ryzykowne" + (", ale ktoś prawdopodobnie ma dużo tego koloru."
                                                    if heavy >= 0.5 else "."))
        else:
            reasons.append("Pozbywam się karty niepunktowanej" + (" (wysokiej)." if r >= 0.6 else "."))
    return Score(scenario, _clamp(corr), _clamp(aggr), reasons, comps)


def _safe_take_value(ctx: Ctx, legal: list[Card]) -> float:
    """0..1: na ile opłacało się zebrać lewę zamiast dokładać pod spód (czysta lewa, niskie ryzyko, wcześnie)."""
    if ctx.rules.trick_penalty(ctx.trick_number) > 0 or any(ctx.pen(c) > 0 for c in ctx.current):
        return 0.0
    takers = [c for c in legal if ctx.beats_current(c) and ctx.pen(c) == 0]
    if not takers:
        return 0.0
    best = max(takers, key=lambda c: c.value)
    return (1 - ctx.risk(best)) * (1 - ctx.progress)


# ---------------------------------------------------------------------------
def _lead(ctx: Ctx, card: Card) -> Score:
    """Ja otwieram lewę: wybór koloru i wysokości karty."""
    P = ctx.params
    suit = card.suit
    counts = Counter(c.suit for c in ctx.hand)
    last_card = counts[suit] == 1
    # ostatnią kartą koloru pozbywam się go - zrzut kar od gracza bez koloru liczy się słabiej
    void_weight = 1 - P.lead_last_card_relief if last_card else 1.0
    p, risk, void = ctx.p_win(card), ctx.risk(card, void_weight), ctx.void_prob(suit)
    corr = 100.0 * (1 - risk)
    reasons = []
    if last_card and p > 0:
        reasons.append("Ostatnia karta w tym kolorze - pozbywam się koloru.")
    if risk >= 0.5:
        reasons.append(f"Wysokie ryzyko wzięcia kar (ryzyko={risk:.2f}): w tym kolorze są jeszcze "
                       "karty punktowane, lewa jest karana albo gracz bez koloru zrzuci mi karę.")

    own_pen = {s: any(ctx.pen(c) > 0 for c in ctx.hand if c.suit == s) for s in counts}
    clean = [s for s in counts if not own_pen[s]]
    danger = (ctx.rules.trick_penalty(ctx.trick_number) > 0
              or any(ctx.pen(c) > 0 for c in ctx.unseen if c.suit == suit))

    if own_pen[suit]:
        if clean:
            corr -= P.lead_own_penalty_loss
            reasons.append("Wychodzę w kolor, w którym mam własne karty punktowane - nic to nie daje.")
        else:
            reasons.append("Każdy mój kolor ma własne karty punktowane - brak lepszej alternatywy.")
    elif counts[suit] == min(counts[s] for s in clean):
        reasons.append("Najkrótszy kolor bez moich kart punktowanych - pozbywam się koloru.")
    elif danger:
        corr -= P.lead_long_suit_loss
        reasons.append("Długi kolor, w którym punktowane karty mają inni - zmuszam ich do wzięcia lewy.")
    else:
        corr -= P.lead_no_danger_loss
        reasons.append("Długi kolor bez kar w grze - nic nie daje; lepiej pozbywać się najkrótszego koloru.")

    if void >= 0.3:
        reasons.append("Sporo tego koloru już zagrano - rośnie szansa, że komuś się skończy.")
    aggr = _intent(ctx, p) + P.void_aggr * void + P.risk_aggr * risk
    return Score("lead", _clamp(corr), _clamp(aggr), reasons,
                 {"p_win": p, "risk": risk, "void_prob": void, "progress": ctx.progress})
