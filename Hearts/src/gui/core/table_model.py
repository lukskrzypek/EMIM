"""Qt-free state of the table view, driven by runner events.

The scene only *reads* this model: where every card is, who may see which hand,
whose turn it is and whether the hot-seat veil is up.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Literal

from gui.core.events import (
    DealFinished,
    DealStarted,
    GameEvent,
    MovePlayed,
    SessionFinished,
    SessionStarted,
    TrickCompleted,
    TurnStarted,
)
from gui.core.snapshot import TableSnapshot


@dataclass(frozen=True)
class CardLocation:
    kind: Literal["hand", "trick", "gone"]
    seat: str  # owner of the hand / player who played it / player who collected it
    index: int = 0  # position in the hand (sorted) or order in the trick
    count: int = 0  # cards in that hand / in that trick


class TableModel:
    """Applies runner events; answers "where is card X" and "who sees what"."""

    def __init__(
        self,
        player_ids: Sequence[str],
        human_ids: Sequence[str],
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._clock = clock  # the session passes ``PaceControl.clock``: it stops while paused
        self.player_ids: tuple[str, ...] = tuple(player_ids)
        self.human_ids: tuple[str, ...] = tuple(human_ids)
        self.seat_labels: dict[str, str] = {pid: pid for pid in self.player_ids}
        self.reveal_bots = False
        self.snapshot: TableSnapshot | None = None
        self.deal_number = 0
        self.total_deals = 1
        self.pending_trick: tuple[tuple[str, str], ...] | None = None
        self.pending_winner: str | None = None
        self.collected: dict[str, str] = {}  # card -> seat that took the trick
        self.all_cards: tuple[str, ...] = ()
        self.tricks: list[tuple[str, ...]] = []  # finished tricks of this deal, in playing order
        self.turn_player: str | None = None
        self.turn_is_human = False
        self.thinking_since: float | None = None
        self.viewer_ack: str | None = None  # hot-seat: human who confirmed the veil last
        self.veil_for: str | None = None
        self.deal_result: DealFinished | None = None
        self.session_result: SessionFinished | None = None

    # ---------------------------------------------------------------- events

    def apply(self, event: GameEvent) -> None:
        if isinstance(event, (TurnStarted, DealStarted, DealFinished, SessionFinished)):
            self._collect_pending()
        if isinstance(event, SessionStarted):
            self.seat_labels = dict(event.seat_labels)
            self.total_deals = event.total_deals
        elif isinstance(event, DealStarted):
            self.snapshot = event.snapshot
            self.deal_number = event.deal_number
            self.total_deals = event.total_deals
            self.collected = {}
            self.tricks = []
            self.pending_trick = self.pending_winner = None
            self.all_cards = tuple(c for hand in event.snapshot.hands.values() for c in hand)
            self.deal_result = None
            self.turn_player, self.turn_is_human, self.thinking_since = None, False, None
        elif isinstance(event, TurnStarted):
            self.snapshot = event.snapshot
            self.turn_player = event.player_id
            self.turn_is_human = event.is_human
            self.thinking_since = None if event.is_human else self._clock()
            if event.is_human and len(self.human_ids) > 1 and self.viewer_ack != event.player_id:
                self.veil_for = event.player_id
            elif event.is_human:
                self.viewer_ack = event.player_id
        elif isinstance(event, MovePlayed):
            self.snapshot = event.snapshot
            self.turn_player, self.turn_is_human, self.thinking_since = None, False, None
        elif isinstance(event, TrickCompleted):
            self.snapshot = event.snapshot
            self.pending_trick = event.cards
            self.pending_winner = event.winner
            self.tricks.append(tuple(card for _, card in event.cards))
        elif isinstance(event, DealFinished):
            self.deal_result = event
            self.turn_player, self.turn_is_human, self.thinking_since = None, False, None
        elif isinstance(event, SessionFinished):
            self.session_result = event
            self.veil_for = None
            self.turn_player, self.turn_is_human, self.thinking_since = None, False, None

    def think_elapsed(self) -> float | None:
        """Seconds the current bot has been thinking (pauses do not count); ``None`` if nobody is."""
        if self.thinking_since is None:
            return None
        return max(0.0, self._clock() - self.thinking_since)

    def _collect_pending(self) -> None:
        if self.pending_trick is None or self.pending_winner is None:
            return
        for _, card in self.pending_trick:
            self.collected[card] = self.pending_winner
        self.pending_trick = self.pending_winner = None

    # ------------------------------------------------------------ visibility

    @property
    def has_humans(self) -> bool:
        return bool(self.human_ids)

    @property
    def hot_seat(self) -> bool:
        """More than one human shares the screen."""
        return len(self.human_ids) > 1

    @property
    def viewer(self) -> str:
        """Seat drawn at the bottom of the table (rotates between hot-seat humans)."""
        if not self.human_ids:
            return self.player_ids[0]
        if self.hot_seat:
            return self.viewer_ack if self.viewer_ack in self.human_ids else self.human_ids[0]
        return self.human_ids[0]

    def face_up(self, pid: str) -> bool:
        if not self.has_humans:
            return True  # nobody has secrets when only bots play
        if pid in self.human_ids:
            if not self.hot_seat:
                return True
            current = self.snapshot.current_player if self.snapshot else None
            return self.veil_for is None and pid == self.viewer_ack and pid == current
        return self.reveal_bots

    def acknowledge_veil(self) -> None:
        if self.veil_for is not None:
            self.viewer_ack, self.veil_for = self.veil_for, None

    @property
    def interactive_player(self) -> str | None:
        """Human who may click a card right now."""
        if self.turn_is_human and self.veil_for is None and self.session_result is None:
            return self.turn_player
        return None

    @property
    def legal_moves(self) -> frozenset[str]:
        if self.interactive_player is None or self.snapshot is None:
            return frozenset()
        return frozenset(self.snapshot.legal_moves)

    # -------------------------------------------------------------- locations

    def card_locations(self) -> dict[str, CardLocation]:
        """Location of each card the scene must place. Cards in limbo (between two
        events of one batch) are left out and simply stay where they are."""
        if self.snapshot is None:
            return {}
        result: dict[str, CardLocation] = {}
        for pid, hand in self.snapshot.hands.items():
            for index, card in enumerate(hand):
                result[card] = CardLocation("hand", pid, index, len(hand))
        trick = self.snapshot.current_trick or ()
        trick = trick if trick else (self.pending_trick or ())
        for order, (pid, card) in enumerate(trick):
            result[card] = CardLocation("trick", pid, order, len(trick))
        for card, taker in self.collected.items():
            result[card] = CardLocation("gone", taker)
        return result

    def points(self, pid: str) -> int:
        return self.snapshot.points.get(pid, 0) if self.snapshot else 0
