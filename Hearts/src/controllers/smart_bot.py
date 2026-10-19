"""Algorithmic Hearts bot: expert heuristics + Monte Carlo over hidden hands (no LLM)."""

from __future__ import annotations

import random
import re
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from controllers.base import PlayerController
from engine.game import (
    QUEEN_OF_SPADES,
    TOTAL_POINTS,
    PlayerObservation,
    _legal_cards,
    card_points,
)
from engine.models import Card, Deck, Rank, Suit

_PLAY_RE = re.compile(r"(P\d+):([2-9TJQKA][CDSH])")
_MAX_DEAL_ATTEMPTS = 40
_RANKS: list[Rank] = list(Rank)

Trick = Sequence[tuple[str, Card]]


# --------------------------------------------------------------- heuristics


def _highest(cards: Sequence[Card]) -> Card:
    return max(cards, key=lambda c: c.rank)


def _lowest(cards: Sequence[Card]) -> Card:
    return min(cards, key=lambda c: c.rank)


def _follow(legal: Sequence[Card], trick: Trick, num_players: int) -> Card:
    """Following suit: duck under the table's top card, else lose as little as possible."""
    lead = trick[0][1].suit
    top = max(c.rank for _, c in trick if c.suit is lead)
    safe = [c for c in legal if c.rank < top]
    if safe:
        return _highest(safe)
    # Forced to take the trick: never volunteer the queen if there is an alternative.
    candidates = [c for c in legal if c != QUEEN_OF_SPADES] or list(legal)
    if len(trick) == num_players - 1:
        return _highest(candidates)  # we win anyway: shed the most dangerous card
    return _lowest(candidates)  # later players may still overtake us


def _dump(legal: Sequence[Card], *, qs_played: bool) -> Card:
    """Void in the led suit: whatever we throw lands on someone else."""
    if QUEEN_OF_SPADES in legal:
        return QUEEN_OF_SPADES
    if not qs_played:
        risky = [c for c in legal if c.suit is Suit.SPADES and c.rank > Rank.QUEEN]
        if risky:
            return _highest(risky)
    hearts = [c for c in legal if c.suit is Suit.HEARTS]
    if hearts:
        return _highest(hearts)
    suit_len = Counter(c.suit for c in legal)
    return max(legal, key=lambda c: (c.rank, -suit_len[c.suit]))


def _lead(legal: Sequence[Card], hand: Sequence[Card], *, qs_played: bool) -> Card:
    """Leading: low cards from the longest safe suit; avoid hearts and spades."""
    plain = [c for c in legal if c.suit not in (Suit.HEARTS, Suit.SPADES)]
    if plain:
        length = Counter(c.suit for c in hand)
        # Longest suit first; on ties start with the suit whose lowest card is lowest.
        lows = {s: _lowest([c for c in plain if c.suit is s]) for s in {c.suit for c in plain}}
        suit = max(lows, key=lambda s: (length[s], -_RANKS.index(lows[s].rank)))
        return lows[suit]

    spades = [c for c in legal if c.suit is Suit.SPADES]
    low_spades = [c for c in spades if qs_played or c.rank < Rank.QUEEN]
    if low_spades:
        return _lowest(low_spades)
    hearts = [c for c in legal if c.suit is Suit.HEARTS]
    if hearts:
        return _lowest(hearts)
    return _lowest([c for c in legal if c != QUEEN_OF_SPADES] or list(legal))


def heuristic_move(
    legal: Sequence[Card],
    hand: Sequence[Card],
    trick: Trick,
    *,
    qs_played: bool,
    num_players: int,
) -> Card:
    """Expert rule-of-thumb choice among ``legal`` (non-empty)."""
    if len(legal) == 1:
        return legal[0]
    if not trick:
        return _lead(legal, hand, qs_played=qs_played)
    if legal[0].suit is trick[0][1].suit:
        return _follow(legal, trick, num_players)
    return _dump(legal, qs_played=qs_played)


# ------------------------------------------------------------ hidden state


@dataclass
class _Context:
    """Everything a player can infer from one observation."""

    player_ids: list[str]
    me: str
    hand: list[Card]
    trick: list[tuple[str, Card]]
    unknown: list[Card]
    capacities: dict[str, int]  # cards still held by each opponent
    voids: dict[str, set[Suit]]
    hearts_broken: bool
    trick_number: int
    base_points: dict[str, int]
    qs_played: bool


def _build_context(observation: PlayerObservation) -> _Context | None:
    """Infer unseen cards and opponent hand sizes; ``None`` if data is inconsistent."""
    n = observation.num_players
    ids = [f"P{i}" for i in range(n)]
    me = observation.player_id
    deck = Deck(n)

    plays: list[tuple[str, Card]] = []
    for line in observation.trick_history:
        plays.extend((p, Card.parse(c)) for p, c in _PLAY_RE.findall(line.split("->")[0]))
    trick = [(p, Card.parse(c)) for p, c in observation.current_trick]
    plays.extend(trick)

    hand = [Card.parse(c) for c in observation.hand]
    seen = {c for _, c in plays} | set(hand)
    unknown = [c for c in deck.cards if c not in seen]

    played_by = Counter(p for p, _ in plays)
    capacities = {
        p: deck.cards_per_player - played_by[p] for p in ids if p != me
    }
    if (
        me not in ids
        or any(v < 0 for v in capacities.values())
        or sum(capacities.values()) != len(unknown)
        or len(hand) != deck.cards_per_player - played_by[me]
    ):
        return None

    voids = {p: {Suit(s) for s in observation.exposed_voids.get(p, [])} for p in ids}
    return _Context(
        player_ids=ids,
        me=me,
        hand=hand,
        trick=trick,
        unknown=unknown,
        capacities=capacities,
        voids=voids,
        hearts_broken=observation.hearts_broken,
        trick_number=observation.trick_number,
        base_points={p: observation.scores.get(p, 0) for p in ids},
        qs_played=any(c == QUEEN_OF_SPADES for _, c in plays),
    )


def _deal_unknown(
    unknown: Sequence[Card],
    capacities: Mapping[str, int],
    voids: Mapping[str, set[Suit]],
    rng: random.Random,
) -> dict[str, list[Card]]:
    """Randomly distribute unseen cards, honouring capacities and exposed voids."""
    eligible_count = {
        suit: sum(1 for p in capacities if suit not in voids.get(p, ())) for suit in Suit
    }
    for _ in range(_MAX_DEAL_ATTEMPTS):
        cards = list(unknown)
        rng.shuffle(cards)
        cards.sort(key=lambda c: eligible_count[c.suit])  # most constrained first
        remaining = dict(capacities)
        hands: dict[str, list[Card]] = {p: [] for p in capacities}
        for card in cards:
            options = [
                p for p, left in remaining.items()
                if left > 0 and card.suit not in voids.get(p, ())
            ]
            if not options:
                break
            chosen = rng.choices(options, weights=[remaining[p] for p in options])[0]
            hands[chosen].append(card)
            remaining[chosen] -= 1
        else:
            return hands

    # Contradictory voids (should not happen): ignore them.
    cards = list(unknown)
    rng.shuffle(cards)
    hands = {}
    start = 0
    for p, size in capacities.items():
        hands[p] = cards[start : start + size]
        start += size
    return hands


# -------------------------------------------------------------- simulation


class _Sim:
    """Minimal hearts state machine used for rollouts (heuristic play for everyone)."""

    def __init__(self, ctx: _Context, hands: dict[str, list[Card]]) -> None:
        self.ids = ctx.player_ids
        self.hands = hands
        self.trick = list(ctx.trick)
        self.hearts_broken = ctx.hearts_broken
        self.trick_number = ctx.trick_number
        self.points = dict(ctx.base_points)
        self.qs_played = ctx.qs_played
        self.current = ctx.me

    def legal(self, pid: str) -> list[Card]:
        return _legal_cards(
            self.hands[pid],
            self.trick,
            first_trick=self.trick_number == 1,
            hearts_broken=self.hearts_broken,
        )

    def play(self, pid: str, card: Card) -> None:
        self.hands[pid].remove(card)
        self.trick.append((pid, card))
        if card.suit is Suit.HEARTS:
            self.hearts_broken = True
        if card == QUEEN_OF_SPADES:
            self.qs_played = True
        if len(self.trick) < len(self.ids):
            self.current = self.ids[(self.ids.index(pid) + 1) % len(self.ids)]
            return
        lead = self.trick[0][1].suit
        winner, _ = max(
            (e for e in self.trick if e[1].suit is lead), key=lambda e: e[1].rank
        )
        self.points[winner] += sum(card_points(c) for _, c in self.trick)
        self.trick = []
        self.trick_number += 1
        self.current = winner

    def run(self) -> None:
        while any(self.hands.values()):
            pid = self.current
            legal = self.legal(pid)
            card = heuristic_move(
                legal,
                self.hands[pid],
                self.trick,
                qs_played=self.qs_played,
                num_players=len(self.ids),
            )
            self.play(pid, card)

    def final_score(self, pid: str) -> int:
        """Deal score of ``pid`` with Shooting the Moon applied."""
        if any(v == TOTAL_POINTS for v in self.points.values()):
            return 0 if self.points[pid] == TOTAL_POINTS else TOTAL_POINTS
        return self.points[pid]


# --------------------------------------------------------------------- bot


class SmartHeartsBot(PlayerController):
    """Heuristics plus Monte Carlo determinization (information-set sampling).

    For every legal card the bot samples ``num_samples`` plausible layouts of the
    unseen cards (respecting exposed voids and hand sizes), plays each deal out
    with the heuristic policy, and picks the card with the lowest average penalty.
    ``heuristic_bias`` is a small penalty (in points) given to any move that
    differs from the rule-based suggestion, so rules win unless simulation
    shows a clear improvement.
    """

    def __init__(
        self,
        num_samples: int = 40,
        *,
        seed: int | None = None,
        rng: random.Random | None = None,
        heuristic_bias: float = 0.15,
    ) -> None:
        self._num_samples = num_samples
        self._rng = rng if rng is not None else random.Random(seed)
        self._bias = heuristic_bias

    def select_move(self, observation: PlayerObservation) -> str:
        legal = observation.legal_moves
        if not legal:
            raise ValueError(f"{observation.player_id} has no legal moves")
        if len(legal) == 1:
            return legal[0]

        legal_cards = sorted(Card.parse(code) for code in legal)
        ctx = _build_context(observation)
        hand = ctx.hand if ctx else [Card.parse(c) for c in observation.hand]
        trick = ctx.trick if ctx else [(p, Card.parse(c)) for p, c in observation.current_trick]
        qs_played = ctx.qs_played if ctx else self._qs_played_fallback(observation)
        suggestion = heuristic_move(
            legal_cards,
            hand,
            trick,
            qs_played=qs_played,
            num_players=observation.num_players,
        )
        if ctx is None or self._num_samples <= 0:
            return str(suggestion)

        totals = dict.fromkeys(legal_cards, 0)
        for _ in range(self._num_samples):
            others = _deal_unknown(ctx.unknown, ctx.capacities, ctx.voids, self._rng)
            for card in legal_cards:
                hands = {p: list(h) for p, h in others.items()}
                hands[ctx.me] = list(ctx.hand)
                sim = _Sim(ctx, hands)
                sim.play(ctx.me, card)
                sim.run()
                totals[card] += sim.final_score(ctx.me)

        def cost(card: Card) -> float:
            penalty = 0.0 if card == suggestion else self._bias
            return totals[card] / self._num_samples + penalty

        return str(min(legal_cards, key=cost))

    @staticmethod
    def _qs_played_fallback(observation: PlayerObservation) -> bool:
        qs = str(QUEEN_OF_SPADES)
        return any(qs in line for line in observation.trick_history) or any(
            c == qs for _, c in observation.current_trick
        )
