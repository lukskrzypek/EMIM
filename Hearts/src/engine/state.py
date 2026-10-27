"""King game engine: a pure, deterministic state machine for a whole match (no I/O).

A match has ``num_players * 7`` deals (SPEC.md, section 2). ``GameState.play_card``
moves the state forward and, when a deal ends, deals the next one by itself.
"""

from __future__ import annotations

import copy
import random
from collections.abc import Sequence
from dataclasses import dataclass, field

from engine.contracts import (
    CONTRACT_ORDER,
    GameContract,
    KING_OF_HEARTS,
    evaluate_trick_penalty,
    legal_cards,
    total_tricks,
    trick_winner,
)
from engine.models import KING_PLAYER_COUNTS, Card, Suit, king_deck
from engine.observation import PlayerObservation

CONTRACTS_PER_PLAYER = len(CONTRACT_ORDER)


class IllegalMoveError(ValueError):
    """Raised when a move violates the rules or the turn order."""


def player_ids_for(num_players: int) -> tuple[str, ...]:
    return tuple(f"P{i}" for i in range(num_players))


@dataclass(frozen=True)
class TrickRecord:
    """A finished trick."""

    deal_number: int
    number: int
    plays: tuple[tuple[str, Card], ...]
    winner: str
    points: int

    def summary(self) -> str:
        plays = ", ".join(f"{p}:{c}" for p, c in self.plays)
        return f"T{self.number}: {plays} -> Win:{self.winner} ({self.points}pts)"


@dataclass(frozen=True)
class DealResult:
    """Penalties of one finished deal."""

    deal_number: int
    contract: GameContract
    declarer: str
    scores: dict[str, int]


@dataclass(frozen=True)
class PlayResult:
    """Outcome of a successful ``play_card`` call."""

    player_id: str
    card: str
    trick_completed: bool = False
    trick_winner: str | None = None
    trick_points: int = 0
    deal_over: bool = False
    game_over: bool = False
    deal_number: int = 1  # the deal the card belongs to
    deal_scores: dict[str, int] | None = None  # set when ``deal_over``


@dataclass(eq=False)
class GameState:
    """Whole match state. Create it with ``GameState.new``."""

    num_players: int
    seed: int
    first_declarer: int
    deal_number: int = 1  # 1..total_deals
    current_contract: GameContract = CONTRACT_ORDER[0]
    declarer: str = "P0"
    hands: dict[str, list[Card]] = field(default_factory=dict)
    current_trick: list[tuple[str, Card]] = field(default_factory=list)
    trick_number: int = 1  # 1..total_tricks
    scores: dict[str, int] = field(default_factory=dict)  # penalties of the current deal
    total_scores: dict[str, int] = field(default_factory=dict)  # penalties of the match
    lead_player: str = "P0"
    current_player: str | None = "P0"  # ``None`` between deals (manual advance) and after the match
    trick_history: list[TrickRecord] = field(default_factory=list)  # current deal
    played_cards: list[tuple[str, Card]] = field(default_factory=list)  # current deal, in order
    voids: dict[str, set[Suit]] = field(default_factory=dict)
    deal_results: list[DealResult] = field(default_factory=list)
    king_of_hearts_played: bool = False
    deal_finished: bool = False  # all tricks played, next deal not started yet (manual advance)
    match_over: bool = False
    # ``True``: the next deal is dealt as soon as a deal ends. ``False``: the finished deal stays
    # visible until ``start_next_deal()`` (a UI wants to show the last trick and the result).
    auto_advance: bool = True

    # ------------------------------------------------------------- creation

    @classmethod
    def new(
        cls,
        num_players: int = 4,
        *,
        seed: int | None = None,
        hands: Sequence[Sequence[str | Card]] | None = None,
        first_declarer: int | None = None,
        start_deal: int = 1,
    ) -> GameState:
        """Start a match.

        ``hands`` fixes the cards of the first dealt deal (tests); ``start_deal``
        begins the match at that deal number (to play a chosen contract).
        """
        if num_players not in KING_PLAYER_COUNTS:
            raise ValueError(f"Player count must be one of {KING_PLAYER_COUNTS}, got {num_players}")
        if seed is None:
            seed = random.SystemRandom().randrange(2**31)
        if first_declarer is None:
            first_declarer = random.Random(f"{seed}:first-declarer").randrange(num_players)
        if not 0 <= first_declarer < num_players:
            raise ValueError(f"first_declarer must be in 0..{num_players - 1}")
        state = cls(num_players, seed, first_declarer)
        if not 1 <= start_deal <= state.total_deals:
            raise ValueError(f"start_deal must be in 1..{state.total_deals}, got {start_deal}")
        state.total_scores = dict.fromkeys(state.player_ids, 0)
        state.deal_number = start_deal
        state._begin_deal(hands)
        return state

    def clone(self) -> GameState:
        """Independent copy (cards are immutable, so lists and dicts are enough)."""
        other = copy.copy(self)
        other.hands = {p: list(h) for p, h in self.hands.items()}
        other.current_trick = list(self.current_trick)
        other.scores = dict(self.scores)
        other.total_scores = dict(self.total_scores)
        other.trick_history = list(self.trick_history)
        other.played_cards = list(self.played_cards)
        other.voids = {p: set(v) for p, v in self.voids.items()}
        other.deal_results = list(self.deal_results)
        return other

    # ----------------------------------------------------------- properties

    @property
    def player_ids(self) -> tuple[str, ...]:
        return player_ids_for(self.num_players)

    @property
    def total_deals(self) -> int:
        return self.num_players * CONTRACTS_PER_PLAYER

    @property
    def total_tricks(self) -> int:
        return total_tricks(self.num_players)

    @property
    def is_over(self) -> bool:
        return self.match_over

    @property
    def final_scores(self) -> dict[str, int] | None:
        """Match totals once the match is over, else ``None``."""
        return dict(self.total_scores) if self.is_over else None

    @property
    def winners(self) -> list[str]:
        """Players with the lowest total (ties allowed); empty until the match is over."""
        if not self.is_over:
            return []
        best = min(self.total_scores.values())
        return [p for p in self.player_ids if self.total_scores[p] == best]

    @property
    def exposed_voids(self) -> dict[str, list[str]]:
        return {p: [s.value for s in sorted(self.voids[p])] for p in self.player_ids}

    # ---------------------------------------------------------------- deals

    def _begin_deal(self, hands: Sequence[Sequence[str | Card]] | None = None) -> None:
        index = self.deal_number - 1
        self.current_contract = CONTRACT_ORDER[index // self.num_players]
        self.declarer = f"P{(self.first_declarer + index) % self.num_players}"
        ids = self.player_ids
        deck = king_deck(self.num_players)
        if hands is None:
            cards = list(deck)
            random.Random(f"{self.seed}:deal:{self.deal_number}").shuffle(cards)
            size = len(cards) // self.num_players
            dealt = [cards[i * size : (i + 1) * size] for i in range(self.num_players)]
        else:
            dealt = self._parse_hands(hands, deck)
        self.hands = {pid: sorted(hand) for pid, hand in zip(ids, dealt, strict=True)}
        self.current_trick = []
        self.trick_number = 1
        self.scores = dict.fromkeys(ids, 0)
        self.voids = {pid: set() for pid in ids}
        self.trick_history = []
        self.played_cards = []
        self.king_of_hearts_played = False
        self.lead_player = self.declarer
        self.current_player = self.declarer
        self.deal_finished = False

    def start_next_deal(self) -> None:
        """Deal the next deal after one has finished (only with ``auto_advance`` off)."""
        if not self.deal_finished or self.match_over:
            raise IllegalMoveError("There is no finished deal to move on from")
        self.deal_number += 1
        self._begin_deal()

    def _parse_hands(
        self, hands: Sequence[Sequence[str | Card]], deck: Sequence[Card]
    ) -> list[list[Card]]:
        if len(hands) != self.num_players:
            raise ValueError(f"Expected {self.num_players} hands, got {len(hands)}")
        parsed = [[c if isinstance(c, Card) else Card.parse(c) for c in hand] for hand in hands]
        flat = [card for hand in parsed for card in hand]
        if len(set(flat)) != len(flat):
            raise ValueError("Duplicate cards in provided hands")
        if set(flat) != set(deck):
            raise ValueError(f"Provided hands must be exactly the {self.num_players}-player deck")
        size = len(deck) // self.num_players
        if any(len(hand) != size for hand in parsed):
            raise ValueError(f"Each hand must have {size} cards")
        return parsed

    # ---------------------------------------------------------------- rules

    def _check_player(self, player_id: str) -> None:
        if player_id not in self.hands:
            raise ValueError(f"Unknown player: {player_id!r}")

    def get_legal_moves(self, player_id: str) -> list[Card]:
        """Cards ``player_id`` may play now. Empty if it is not their turn."""
        self._check_player(player_id)
        if self.current_player is None or player_id != self.current_player:
            return []
        return legal_cards(
            self.hands[player_id],
            self.current_trick,
            self.current_contract,
            king_of_hearts_played=self.king_of_hearts_played,
        )

    def evaluate_trick_penalty(
        self, trick_cards: Sequence[Card], trick_num: int, contract: GameContract
    ) -> int:
        """Positive penalty for taking this trick in ``contract`` (SPEC section 2.2)."""
        return evaluate_trick_penalty(trick_cards, trick_num, contract, self.total_tricks)

    def play_card(self, player_id: str, card: Card | str) -> PlayResult:
        """Play a card, update the trick, and settle the trick / deal / match if complete."""
        self._check_player(player_id)
        if self.match_over:
            raise IllegalMoveError("The match is over")
        if self.deal_finished:
            raise IllegalMoveError("The deal is over; call start_next_deal()")
        if player_id != self.current_player:
            raise IllegalMoveError(f"Not {player_id}'s turn (current: {self.current_player})")
        if isinstance(card, str):
            card = Card.parse(card)
        hand = self.hands[player_id]
        if card not in hand:
            raise IllegalMoveError(f"{player_id} does not hold {card}")
        if card not in self.get_legal_moves(player_id):
            raise IllegalMoveError(f"{card} is not a legal move for {player_id}")

        if self.current_trick:
            lead_suit = self.current_trick[0][1].suit
            if card.suit is not lead_suit:
                self.voids[player_id].add(lead_suit)
        if card == KING_OF_HEARTS:
            self.king_of_hearts_played = True

        hand.remove(card)
        self.current_trick.append((player_id, card))
        self.played_cards.append((player_id, card))

        if len(self.current_trick) < self.num_players:
            self.current_player = self._next_player(player_id)
            return PlayResult(player_id, str(card), deal_number=self.deal_number)
        return self._finish_trick(player_id, card)

    def _next_player(self, player_id: str) -> str:
        index = int(player_id[1:])
        return f"P{(index + 1) % self.num_players}"

    def _finish_trick(self, player_id: str, card: Card) -> PlayResult:
        trick = tuple(self.current_trick)
        winner = trick_winner(trick)
        points = self.evaluate_trick_penalty(
            [c for _, c in trick], self.trick_number, self.current_contract
        )
        self.scores[winner] += points
        self.trick_history.append(
            TrickRecord(self.deal_number, self.trick_number, trick, winner, points)
        )
        self.current_trick = []
        finished_deal = self.deal_number

        if any(self.hands.values()):
            self.trick_number += 1
            self.lead_player = winner
            self.current_player = winner
            return PlayResult(
                player_id,
                str(card),
                trick_completed=True,
                trick_winner=winner,
                trick_points=points,
                deal_number=finished_deal,
            )

        deal_scores = dict(self.scores)
        for pid, penalty in deal_scores.items():
            self.total_scores[pid] += penalty
        self.deal_results.append(
            DealResult(finished_deal, self.current_contract, self.declarer, deal_scores)
        )
        game_over = finished_deal == self.total_deals
        if game_over:
            self.match_over = True
            self.deal_finished = True
            self.current_player = None
        elif self.auto_advance:
            self.deal_number += 1
            self._begin_deal()
        else:
            self.deal_finished = True
            self.current_player = None
        return PlayResult(
            player_id,
            str(card),
            trick_completed=True,
            trick_winner=winner,
            trick_points=points,
            deal_over=True,
            game_over=game_over,
            deal_number=finished_deal,
            deal_scores=deal_scores,
        )

    # ---------------------------------------------------------- observation

    def get_player_observation(self, player_id: str) -> PlayerObservation:
        self._check_player(player_id)
        return PlayerObservation(
            player_id=player_id,
            hand=[str(c) for c in sorted(self.hands[player_id])],
            current_trick=[(p, str(c)) for p, c in self.current_trick],
            trick_history=[record.summary() for record in self.trick_history],
            exposed_voids=self.exposed_voids,
            scores=dict(self.scores),
            legal_moves=[str(c) for c in self.get_legal_moves(player_id)],
            total_scores=dict(self.total_scores),
            played_cards=[(p, str(c)) for p, c in self.played_cards],
            contract=self.current_contract,
            declarer=self.declarer,
            deal_number=self.deal_number,
            total_deals=self.total_deals,
            trick_number=self.trick_number,
            total_tricks=self.total_tricks,
            current_player=self.current_player,
            game_over=self.is_over,
            num_players=self.num_players,
        )


def schedule(num_players: int, first_declarer: int) -> list[tuple[GameContract, str]]:
    """(contract, declarer) of every deal of a match, in order (SPEC section 2.1)."""
    return [
        (CONTRACT_ORDER[d // num_players], f"P{(first_declarer + d) % num_players}")
        for d in range(num_players * CONTRACTS_PER_PLAYER)
    ]


__all__ = [
    "GameState",
    "IllegalMoveError",
    "DealResult",
    "PlayResult",
    "TrickRecord",
    "schedule",
    "player_ids_for",
]
