"""King (Kierki polskie) contracts: penalties, legal moves and trick winner.

Pure functions only. Every rule that depends on the contract lives here, so the
engine, the bots and the evaluation module share one definition (SPEC.md, sections 2-3).
"""

from __future__ import annotations

from collections.abc import Sequence
from enum import Enum

from engine.models import Card, Rank, Suit, king_hand_size


class GameContract(Enum):
    NO_TRICKS = "NO_TRICKS"
    NO_HEARTS = "NO_HEARTS"
    NO_QUEENS = "NO_QUEENS"
    NO_MEN = "NO_MEN"
    NO_KING_OF_HEARTS = "NO_KING_OF_HEARTS"
    NO_7TH_AND_LAST = "NO_7TH_AND_LAST"
    ROBBER = "ROBBER"


# Fixed order of a match: each contract is played once per declarer (SPEC 2.1).
CONTRACT_ORDER: tuple[GameContract, ...] = tuple(GameContract)
DEALS_PER_GAME = len(CONTRACT_ORDER)  # one deal of each contract, in this order

PENALTY_TRICK = 20  # NO_TRICKS: every trick taken
PENALTY_HEART = 20  # NO_HEARTS: every heart taken
PENALTY_QUEEN = 60  # NO_QUEENS: every queen taken
PENALTY_MAN = 30  # NO_MEN: every king and jack taken
PENALTY_KING_OF_HEARTS = 150  # NO_KING_OF_HEARTS: KH taken
PENALTY_SPECIAL_TRICK = 75  # NO_7TH_AND_LAST: the 7th trick and the last one
SEVENTH_TRICK = 7

KING_OF_HEARTS = Card(Suit.HEARTS, Rank.KING)
# Contracts in which a player may not lead a heart while holding another suit
# (until KH has been played).
HEART_LEAD_RESTRICTED: frozenset[GameContract] = frozenset(
    {GameContract.NO_HEARTS, GameContract.NO_KING_OF_HEARTS, GameContract.ROBBER}
)

_CARD_CONTRACTS = frozenset(set(GameContract) - {GameContract.NO_TRICKS, GameContract.NO_7TH_AND_LAST})


def total_tricks(num_players: int) -> int:
    """Number of tricks in one deal: 13 for 4 players, 17 for 3."""
    return king_hand_size(num_players)


def card_penalty(card: Card, contract: GameContract) -> int:
    """Penalty of taking ``card`` in a trick (the trick-number part is separate)."""
    if contract not in _CARD_CONTRACTS:
        return 0
    penalty = 0
    robber = contract is GameContract.ROBBER
    if card.suit is Suit.HEARTS and (robber or contract is GameContract.NO_HEARTS):
        penalty += PENALTY_HEART
    if card.rank is Rank.QUEEN and (robber or contract is GameContract.NO_QUEENS):
        penalty += PENALTY_QUEEN
    if card.rank in (Rank.KING, Rank.JACK) and (robber or contract is GameContract.NO_MEN):
        penalty += PENALTY_MAN
    if card == KING_OF_HEARTS and (robber or contract is GameContract.NO_KING_OF_HEARTS):
        penalty += PENALTY_KING_OF_HEARTS
    return penalty


def trick_number_penalty(trick_num: int, tricks_in_deal: int, contract: GameContract) -> int:
    """Penalty of taking trick number ``trick_num`` (1-based) regardless of its cards."""
    penalty = 0
    if contract in (GameContract.NO_TRICKS, GameContract.ROBBER):
        penalty += PENALTY_TRICK
    if contract in (GameContract.NO_7TH_AND_LAST, GameContract.ROBBER) and trick_num in (
        SEVENTH_TRICK,
        tricks_in_deal,
    ):
        penalty += PENALTY_SPECIAL_TRICK
    return penalty


def evaluate_trick_penalty(
    trick_cards: Sequence[Card],
    trick_num: int,
    contract: GameContract,
    tricks_in_deal: int = 13,
) -> int:
    """Positive penalty for whoever takes this trick in ``contract``."""
    return trick_number_penalty(trick_num, tricks_in_deal, contract) + sum(
        card_penalty(card, contract) for card in trick_cards
    )


def contract_total_penalty(contract: GameContract, num_players: int) -> int:
    """Sum of all penalties handed out in one deal of ``contract`` (a constant)."""
    tricks = total_tricks(num_players)
    deck_cards = [
        Card(suit, rank)
        for suit in Suit
        for rank in Rank
        if not (num_players == 3 and suit is Suit.CLUBS and rank is Rank.TWO)
    ]
    cards = sum(card_penalty(card, contract) for card in deck_cards)
    numbers = sum(trick_number_penalty(n, tricks, contract) for n in range(1, tricks + 1))
    return cards + numbers


def legal_cards(
    hand: Sequence[Card],
    trick: Sequence[tuple[str, Card]],
    contract: GameContract,
    *,
    king_of_hearts_played: bool,
) -> list[Card]:
    """Playable cards (sorted) according to SPEC section 3."""
    if not trick:
        if contract in HEART_LEAD_RESTRICTED and not king_of_hearts_played:
            others = [c for c in hand if c.suit is not Suit.HEARTS]
            if others:
                return sorted(others)
        return sorted(hand)
    lead_suit = trick[0][1].suit
    following = [c for c in hand if c.suit is lead_suit]
    return sorted(following) if following else sorted(hand)


def trick_winner(trick: Sequence[tuple[str, Card]]) -> str:
    """Player who played the highest card of the led suit."""
    lead_suit = trick[0][1].suit
    best_player, best_card = trick[0]
    for player, card in trick[1:]:
        if card.suit is lead_suit and card.value > best_card.value:
            best_player, best_card = player, card
    return best_player
