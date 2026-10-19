"""Hearts game engine: a pure state machine for a single deal (no I/O)."""

from __future__ import annotations

import random
from collections.abc import Sequence
from dataclasses import dataclass, field

from engine.models import Card, Deck, Suit

SUPPORTED_PLAYER_COUNTS: tuple[int, ...] = (2, 3, 4, 5)
TOTAL_POINTS: int = 26
QUEEN_OF_SPADES: Card = Card.parse("QS")
TWO_OF_CLUBS: Card = Card.parse("2C")


class IllegalMoveError(ValueError):
    """Raised when a move violates the rules or the turn order."""


def card_points(card: Card) -> int:
    """Penalty value: each heart is 1, the queen of spades is 13."""
    if card.suit is Suit.HEARTS:
        return 1
    if card == QUEEN_OF_SPADES:
        return 13
    return 0


def _legal_cards(
    hand: Sequence[Card],
    trick: Sequence[tuple[str, Card]],
    *,
    first_trick: bool,
    hearts_broken: bool,
) -> list[Card]:
    """Apply SPEC section 3 to a hand and return the playable cards (sorted)."""
    if not trick:
        if first_trick:
            return [TWO_OF_CLUBS] if TWO_OF_CLUBS in hand else []
        non_hearts = [c for c in hand if c.suit is not Suit.HEARTS]
        if hearts_broken or not non_hearts:
            return sorted(hand)
        return sorted(non_hearts)

    lead_suit = trick[0][1].suit
    following = [c for c in hand if c.suit is lead_suit]
    if following:
        return sorted(following)
    if first_trick:
        non_points = [c for c in hand if card_points(c) == 0]
        if non_points:
            return sorted(non_points)
    return sorted(hand)


@dataclass
class PlayerObservation:
    """What a single player (or an LLM acting as one) is allowed to see."""

    player_id: str
    hand: list[str]
    current_trick: list[tuple[str, str]]
    trick_history: list[str]
    exposed_voids: dict[str, list[str]]
    hearts_broken: bool
    scores: dict[str, int]
    legal_moves: list[str]
    trick_number: int = 1
    current_player: str | None = None
    game_over: bool = False
    num_players: int = field(default=4)

    def to_icl_prompt(self, max_history: int = 8) -> str:
        """Compact text block (at most ``7 + max_history`` lines)."""
        turn = self.current_player or "-"
        header = (
            f"HEARTS {self.num_players}p | You: {self.player_id} | "
            f"Trick {self.trick_number} | Turn: {turn} | "
            f"Hearts broken: {'yes' if self.hearts_broken else 'no'}"
        )
        if self.game_over:
            header = f"HEARTS {self.num_players}p | You: {self.player_id} | GAME OVER"

        trick = " ".join(f"{p}:{c}" for p, c in self.current_trick) or "(empty)"
        legal = " ".join(self.legal_moves) or "-"
        voids = " ".join(
            f"{p}:{''.join(suits) or '-'}" for p, suits in self.exposed_voids.items()
        )
        scores_label = "Final scores" if self.game_over else "Scores"
        scores = " ".join(f"{p}={pts}" for p, pts in self.scores.items())

        lines = [
            header,
            f"Hand: {' '.join(self.hand) or '-'}",
            f"Trick: {trick}",
            f"Legal: {legal}",
            f"Voids: {voids}",
            f"{scores_label}: {scores}",
        ]
        history = self.trick_history
        if history:
            shown = history[-max_history:] if max_history > 0 else []
            if len(shown) < len(history):
                lines.append(f"History (last {len(shown)} of {len(history)}):")
            else:
                lines.append("History:")
            lines.extend(shown)
        else:
            lines.append("History: (none)")
        return "\n".join(lines)


@dataclass(frozen=True)
class PlayResult:
    """Outcome of a successful ``play_card`` call."""

    player_id: str
    card: str
    trick_completed: bool = False
    trick_winner: str | None = None
    trick_points: int = 0
    hand_over: bool = False


class HeartsGameEngine:
    """Single-deal Hearts for 2-5 players. Players are named ``P0``, ``P1``, ..."""

    def __init__(
        self,
        num_players: int = 4,
        *,
        seed: int | None = None,
        rng: random.Random | None = None,
        hands: Sequence[Sequence[str]] | None = None,
    ) -> None:
        if num_players not in SUPPORTED_PLAYER_COUNTS:
            raise ValueError(
                f"Player count must be one of {SUPPORTED_PLAYER_COUNTS}, got {num_players}"
            )
        self.num_players: int = num_players
        self.player_ids: tuple[str, ...] = tuple(f"P{i}" for i in range(num_players))
        deck = Deck(num_players)

        if hands is None:
            dealt = deck.deal(rng if rng is not None else random.Random(seed))
        else:
            dealt = self._parse_hands(hands, deck)

        self._hands: dict[str, list[Card]] = {
            pid: list(hand) for pid, hand in zip(self.player_ids, dealt, strict=True)
        }
        self._trick: list[tuple[str, Card]] = []
        self._history: list[str] = []
        self._voids: dict[str, set[Suit]] = {pid: set() for pid in self.player_ids}
        self._points: dict[str, int] = {pid: 0 for pid in self.player_ids}
        self._hearts_broken: bool = False
        self._trick_number: int = 1
        self._final_scores: dict[str, int] | None = None
        self._shot_the_moon: str | None = None
        self._current: str | None = next(
            pid for pid, hand in self._hands.items() if TWO_OF_CLUBS in hand
        )

    # ------------------------------------------------------------------ setup

    def _parse_hands(self, hands: Sequence[Sequence[str]], deck: Deck) -> list[list[Card]]:
        if len(hands) != self.num_players:
            raise ValueError(f"Expected {self.num_players} hands, got {len(hands)}")
        parsed = [[Card.parse(code) for code in hand] for hand in hands]
        flat = [card for hand in parsed for card in hand]
        if len(set(flat)) != len(flat):
            raise ValueError("Duplicate cards in provided hands")
        if set(flat) != set(deck.cards):
            raise ValueError(f"Provided hands must be exactly the {self.num_players}-player deck")
        if any(len(hand) != deck.cards_per_player for hand in parsed):
            raise ValueError(f"Each hand must have {deck.cards_per_player} cards")
        return [sorted(hand) for hand in parsed]

    # ------------------------------------------------------------- properties

    @property
    def current_player(self) -> str | None:
        """Player to move, or ``None`` when the deal is over."""
        return self._current

    @property
    def is_over(self) -> bool:
        return self._final_scores is not None

    @property
    def hearts_broken(self) -> bool:
        return self._hearts_broken

    @property
    def trick_number(self) -> int:
        return self._trick_number

    @property
    def points_taken(self) -> dict[str, int]:
        """Raw penalty points collected so far (before Shooting the Moon)."""
        return dict(self._points)

    @property
    def final_scores(self) -> dict[str, int] | None:
        """Deal result with Shooting the Moon applied; ``None`` until the deal ends."""
        return None if self._final_scores is None else dict(self._final_scores)

    @property
    def shot_the_moon(self) -> str | None:
        return self._shot_the_moon

    @property
    def exposed_voids(self) -> dict[str, list[str]]:
        return {
            pid: [suit.value for suit in sorted(suits)] for pid, suits in self._voids.items()
        }

    # ------------------------------------------------------------------ rules

    def _check_player(self, player_id: str) -> None:
        if player_id not in self._hands:
            raise ValueError(f"Unknown player: {player_id!r}")

    def get_legal_moves(self, player_id: str) -> list[str]:
        """Cards ``player_id`` may play now. Empty if it is not their turn."""
        self._check_player(player_id)
        if self.is_over or player_id != self._current:
            return []
        cards = _legal_cards(
            self._hands[player_id],
            self._trick,
            first_trick=self._trick_number == 1,
            hearts_broken=self._hearts_broken,
        )
        return [str(card) for card in cards]

    def play_card(self, player_id: str, card_str: str) -> PlayResult:
        """Play a card, update the trick, and settle the trick / deal if complete."""
        self._check_player(player_id)
        if self.is_over:
            raise IllegalMoveError("The deal is over")
        if player_id != self._current:
            raise IllegalMoveError(f"Not {player_id}'s turn (current: {self._current})")
        card = Card.parse(card_str)
        hand = self._hands[player_id]
        if card not in hand:
            raise IllegalMoveError(f"{player_id} does not hold {card}")
        if str(card) not in self.get_legal_moves(player_id):
            raise IllegalMoveError(f"{card} is not a legal move for {player_id}")

        if self._trick:
            lead_suit = self._trick[0][1].suit
            if card.suit is not lead_suit:
                self._voids[player_id].add(lead_suit)
        if card.suit is Suit.HEARTS:
            self._hearts_broken = True

        hand.remove(card)
        self._trick.append((player_id, card))

        if len(self._trick) < self.num_players:
            self._current = self._next_player(player_id)
            return PlayResult(player_id, str(card))
        return self._finish_trick(player_id, card)

    def _next_player(self, player_id: str) -> str:
        index = self.player_ids.index(player_id)
        return self.player_ids[(index + 1) % self.num_players]

    def _finish_trick(self, player_id: str, card: Card) -> PlayResult:
        lead_suit = self._trick[0][1].suit
        winner, _ = max(
            (entry for entry in self._trick if entry[1].suit is lead_suit),
            key=lambda entry: entry[1].rank,
        )
        points = sum(card_points(c) for _, c in self._trick)
        self._points[winner] += points
        plays = ", ".join(f"{p}:{c}" for p, c in self._trick)
        self._history.append(f"T{self._trick_number}: {plays} -> Win:{winner} ({points}pts)")
        self._trick = []

        hand_over = not any(self._hands.values())
        if hand_over:
            self._settle_deal()
            self._current = None
        else:
            self._trick_number += 1
            self._current = winner
        return PlayResult(
            player_id,
            str(card),
            trick_completed=True,
            trick_winner=winner,
            trick_points=points,
            hand_over=hand_over,
        )

    def _settle_deal(self) -> None:
        scores = dict(self._points)
        mooner = next((p for p, pts in scores.items() if pts == TOTAL_POINTS), None)
        if mooner is not None:
            scores = {p: 0 if p == mooner else TOTAL_POINTS for p in scores}
            self._shot_the_moon = mooner
        self._final_scores = scores

    # ------------------------------------------------------------ observation

    def get_player_observation(self, player_id: str) -> PlayerObservation:
        self._check_player(player_id)
        scores = self._final_scores if self._final_scores is not None else self._points
        return PlayerObservation(
            player_id=player_id,
            hand=[str(c) for c in sorted(self._hands[player_id])],
            current_trick=[(p, str(c)) for p, c in self._trick],
            trick_history=list(self._history),
            exposed_voids=self.exposed_voids,
            hearts_broken=self._hearts_broken,
            scores=dict(scores),
            legal_moves=self.get_legal_moves(player_id),
            trick_number=self._trick_number,
            current_player=self._current,
            game_over=self.is_over,
            num_players=self.num_players,
        )
