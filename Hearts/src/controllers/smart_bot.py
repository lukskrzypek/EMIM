"""Algorithmic King bot: contract-aware heuristics + Monte Carlo over hidden hands (no LLM).

All rules (legal moves, trick winner, penalties) come from ``engine.contracts``; this
module only decides which legal card to play.
"""

from __future__ import annotations

import random
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from controllers.base import PlayerController
from engine.contracts import (
    KING_OF_HEARTS,
    GameContract,
    card_penalty,
    evaluate_trick_penalty,
    legal_cards,
    trick_winner,
)
from engine.models import Card, Suit, king_deck, king_hand_size
from engine.observation import PlayerObservation

_MAX_DEAL_ATTEMPTS = 40

Trick = Sequence[tuple[str, Card]]


# --------------------------------------------------------------- heuristics


def _highest(cards: Sequence[Card]) -> Card:
    return max(cards, key=lambda c: c.value)


def _follow(
    legal: Sequence[Card],
    trick: Trick,
    contract: GameContract,
    num_players: int,
) -> Card:
    """Following suit: duck under the table's top card (dumping penalty cards if possible)."""
    lead = trick[0][1].suit
    top = max(c.value for _, c in trick if c.suit is lead)
    safe = [c for c in legal if c.value < top]
    if safe:
        return max(safe, key=lambda c: (card_penalty(c, contract), c.value))
    # Forced to take the trick unless someone behind us plays higher.
    if len(trick) == num_players - 1:  # last to play: we win, so shed the harmless high card
        return min(legal, key=lambda c: (card_penalty(c, contract), -c.value))
    return min(legal, key=lambda c: (card_penalty(c, contract), c.value))


def _dump(legal: Sequence[Card], contract: GameContract) -> Card:
    """Void in the led suit: whatever we throw lands on someone else."""
    return max(legal, key=lambda c: (card_penalty(c, contract), c.value))


def _lead(legal: Sequence[Card], hand: Sequence[Card], contract: GameContract) -> Card:
    """Leading: the lowest harmless card, from the longest suit on ties."""
    clean = [c for c in legal if card_penalty(c, contract) == 0] or list(legal)
    length = Counter(c.suit for c in hand)
    return min(clean, key=lambda c: (c.value, -length[c.suit]))


def heuristic_move(
    legal: Sequence[Card],
    hand: Sequence[Card],
    trick: Trick,
    contract: GameContract,
    *,
    num_players: int,
) -> Card:
    """Rule-of-thumb choice among ``legal`` (non-empty): stay out of penalties."""
    if len(legal) == 1:
        return legal[0]
    if not trick:
        return _lead(legal, hand, contract)
    if legal[0].suit is trick[0][1].suit:
        return _follow(legal, trick, contract, num_players)
    return _dump(legal, contract)


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
    contract: GameContract
    trick_number: int
    total_tricks: int
    base_points: dict[str, int]  # penalties already taken in this deal
    king_of_hearts_played: bool


def _build_context(observation: PlayerObservation) -> _Context | None:
    """Infer unseen cards and opponent hand sizes; ``None`` if data is inconsistent."""
    n = observation.num_players
    ids = [f"P{i}" for i in range(n)]
    me = observation.player_id
    deck = king_deck(n)
    size = king_hand_size(n)

    plays = [(p, Card.parse(c)) for p, c in observation.played_cards]
    trick = [(p, Card.parse(c)) for p, c in observation.current_trick]
    hand = [Card.parse(c) for c in observation.hand]
    seen = {c for _, c in plays} | set(hand)
    unknown = [c for c in deck if c not in seen]

    played_by = Counter(p for p, _ in plays)
    capacities = {p: size - played_by[p] for p in ids if p != me}
    if (
        me not in ids
        or any(v < 0 for v in capacities.values())
        or sum(capacities.values()) != len(unknown)
        or len(hand) != size - played_by[me]
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
        contract=observation.contract,
        trick_number=observation.trick_number,
        total_tricks=observation.total_tricks,
        base_points={p: observation.scores.get(p, 0) for p in ids},
        king_of_hearts_played=any(c == KING_OF_HEARTS for _, c in plays),
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


class _Rollout:
    """Plays the rest of one deal with the heuristic policy for every seat.

    Only the turn mechanics live here; legality, the trick winner and penalties are
    the engine's functions.
    """

    def __init__(self, ctx: _Context, hands: dict[str, list[Card]]) -> None:
        self.ids = ctx.player_ids
        self.contract = ctx.contract
        self.total_tricks = ctx.total_tricks
        self.hands = hands
        self.trick = list(ctx.trick)
        self.trick_number = ctx.trick_number
        self.points = dict(ctx.base_points)
        self.king_of_hearts_played = ctx.king_of_hearts_played
        self.current = ctx.me

    def legal(self, pid: str) -> list[Card]:
        return legal_cards(
            self.hands[pid],
            self.trick,
            self.contract,
            king_of_hearts_played=self.king_of_hearts_played,
        )

    def play(self, pid: str, card: Card) -> None:
        self.hands[pid].remove(card)
        self.trick.append((pid, card))
        if card == KING_OF_HEARTS:
            self.king_of_hearts_played = True
        if len(self.trick) < len(self.ids):
            self.current = self.ids[(self.ids.index(pid) + 1) % len(self.ids)]
            return
        winner = trick_winner(self.trick)
        self.points[winner] += evaluate_trick_penalty(
            [c for _, c in self.trick], self.trick_number, self.contract, self.total_tricks
        )
        self.trick = []
        self.trick_number += 1
        self.current = winner

    def run(self) -> None:
        while any(self.hands.values()):
            pid = self.current
            card = heuristic_move(
                self.legal(pid),
                self.hands[pid],
                self.trick,
                self.contract,
                num_players=len(self.ids),
            )
            self.play(pid, card)


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

    model_name = "smart_bot"

    def __init__(
        self,
        num_samples: int = 40,
        *,
        seed: int | None = None,
        rng: random.Random | None = None,
        heuristic_bias: float = 3.0,
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

        legal_cards_ = sorted(Card.parse(code) for code in legal)
        ctx = _build_context(observation)
        hand = ctx.hand if ctx else [Card.parse(c) for c in observation.hand]
        trick = ctx.trick if ctx else [(p, Card.parse(c)) for p, c in observation.current_trick]
        suggestion = heuristic_move(
            legal_cards_, hand, trick, observation.contract, num_players=observation.num_players
        )
        if ctx is None or self._num_samples <= 0:
            return str(suggestion)

        totals = dict.fromkeys(legal_cards_, 0)
        for _ in range(self._num_samples):
            others = _deal_unknown(ctx.unknown, ctx.capacities, ctx.voids, self._rng)
            for card in legal_cards_:
                hands = {p: list(h) for p, h in others.items()}
                hands[ctx.me] = list(ctx.hand)
                sim = _Rollout(ctx, hands)
                sim.play(ctx.me, card)
                sim.run()
                totals[card] += sim.points[ctx.me]

        def cost(card: Card) -> float:
            penalty = 0.0 if card == suggestion else self._bias
            return totals[card] / self._num_samples + penalty

        return str(min(legal_cards_, key=cost))
