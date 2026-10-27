"""Stan gry, walidacja wejścia i obliczenia pomocnicze (prawdopodobieństwa, ryzyko)."""
from __future__ import annotations

import math
from dataclasses import dataclass, field

from .cards import Card, full_deck, parse_card, total_tricks
from .params import Params
from engine.contracts import GameContract

from .rounds import RoundRules, get_rules


class InvalidState(ValueError):
    """Niespójne dane wejściowe (to nie jest błąd ruchu gracza)."""


@dataclass
class GameState:
    hand: list[str]                      # ręka gracza PRZED zagraniem (z kartą do oceny)
    contract: GameContract
    history: list[list[str]] = field(default_factory=list)   # zakończone lewy, w kolejności kładzenia
    current_trick: list[str] = field(default_factory=list)   # karty już leżące w bieżącej lewie
    num_players: int = 4                   # 3-4 (3 graczy: 17 lew, talia bez 2C)
    legal_moves: list[str] | None = None   # legalne karty wg silnika; None = tylko zasada "dokładaj do koloru"


@dataclass
class Ctx:
    hand: list[Card]
    current: list[Card]
    unseen: list[Card]          # karty, których gracz nie widzi (są na rękach przeciwników)
    rules: RoundRules
    params: Params
    trick_number: int           # 1..13
    n_remaining: int            # ilu graczy zagra PO mnie w tej lewie
    ref_penalty: float          # "zła lewa": kara za lewę + najwyższa pojedyncza karta (normalizacja ryzyka)
    total_tricks: int = 13
    legal: list[Card] | None = None   # legalne karty podane z zewnątrz (reguły silnika)

    # ---------- podstawowe ----------
    @property
    def h(self) -> int:
        return len(self.hand)

    @property
    def progress(self) -> float:
        """0 w pierwszej lewie, 1 w ostatniej."""
        return (self.trick_number - 1) / (self.total_tricks - 1)

    @property
    def lead_suit(self) -> str | None:
        return self.current[0].suit if self.current else None

    def pen(self, card: Card) -> int:
        return self.rules.card_penalty(card)

    def legal_cards(self) -> list[Card]:
        if self.legal is not None:
            return list(self.legal)
        if not self.current:
            return list(self.hand)
        same = [c for c in self.hand if c.suit == self.lead_suit]
        return same or list(self.hand)

    def beats_current(self, card: Card) -> bool:
        """Czy karta otwiera lewę albo bije aktualnie prowadzącą kartę."""
        if not self.current:
            return True
        if card.suit != self.lead_suit:
            return False
        best = max(c.value for c in self.current if c.suit == self.lead_suit)
        return card.value > best

    def _unseen_in_suit(self, suit: str) -> int:
        return sum(1 for c in self.unseen if c.suit == suit)

    def sure_win(self, card: Card) -> bool:
        """Karta na pewno weźmie lewę (nikt po mnie nie może jej przebić)."""
        if not self.beats_current(card):
            return False
        if self.n_remaining == 0:
            return True
        return not any(c.suit == card.suit and c.value > card.value for c in self.unseen)

    # ---------- prawdopodobieństwa ----------
    def p_win(self, card: Card) -> float:
        """P(wezmę lewę tą kartą)."""
        if not self.beats_current(card):
            return 0.0
        if self.n_remaining == 0:
            return 1.0
        k = sum(1 for c in self.unseen if c.suit == card.suit and c.value > card.value)
        if k == 0:
            return 1.0
        u = len(self.unseen)
        m = min(self.n_remaining * self.h, u)  # karty graczy, którzy jeszcze zagrają w tej lewie
        # P(żaden z nich nie ma wyższej karty do koloru) - losowe rozdanie, bez wiedzy o renonsach
        p_none = math.comb(u - k, m) / math.comb(u, m) if u - k >= m else 0.0
        e = min(k, self.n_remaining)  # przybliżona liczba graczy, którzy mogą przebić
        return p_none + (1.0 - p_none) * (1.0 - self.params.overtake_rate) ** e

    def _p_void(self, suit: str, hand_size: int) -> float:
        u, total = self._unseen_in_suit(suit), len(self.unseen)
        if total - u < hand_size:
            return 0.0
        return math.comb(total - u, hand_size) / math.comb(total, hand_size)

    def void_prob(self, suit: str) -> float:
        """P(przynajmniej jednemu z graczy po mnie skończył się ten kolor)."""
        if self.n_remaining == 0:
            return 0.0
        pv = self._p_void(suit, self.h)
        return 1.0 - (1.0 - pv) ** self.n_remaining

    def heavy_prob(self, suit: str) -> float:
        """P(któryś z przeciwników ma "dużo" kart tego koloru) - patrz Params.heavy_*."""
        u, total = self._unseen_in_suit(suit), len(self.unseen)
        if u == 0 or total == 0:
            return 0.0
        P = self.params
        sizes = [self.h - 1] * len(self.current) + [self.h] * self.n_remaining
        none = 1.0
        for a in sizes:
            if a <= 0:
                continue
            t = max(P.heavy_min_cards, math.ceil(P.heavy_fraction * a))
            tail = sum(math.comb(u, j) * math.comb(total - u, a - j) for j in range(t, min(u, a) + 1))
            none *= 1.0 - tail / math.comb(total, a)
        return 1.0 - none

    # ---------- ryzyko wzięcia kar ----------
    def expected_trick_penalty(self, card: Card, void_weight: float = 1.0) -> float:
        """Oczekiwana kara w lewie, jeśli ją wezmę zagraną kartą (znane karty + zrzuty następnych graczy).

        void_weight skaluje składnik "gracz bez koloru zrzuca mi karę"."""
        P = self.params
        suit = self.lead_suit or card.suit
        known = (self.rules.trick_penalty(self.trick_number)
                 + sum(self.pen(c) for c in self.current) + self.pen(card))
        total = len(self.unseen)
        if self.n_remaining == 0 or total == 0:
            return float(known)
        # karty punktowane tego samego koloru, które mogą trafić do lewy od graczy po mnie
        share = min(1.0, self.n_remaining * self.h / total)
        same = sum(self.pen(c) for c in self.unseen if c.suit == suit)
        e_same = P.attack_rate * share * same
        # gracz bez koloru może zrzucić mi dowolną punktowaną kartę
        others = [self.pen(c) for c in self.unseen if c.suit != suit and self.pen(c) > 0]
        e_void = 0.0
        if others:
            mean_pen = sum(others) / len(others)
            p_has = min(1.0, self.h * len(others) / total)
            e_void = P.attack_rate * self.void_prob(suit) * p_has * mean_pen
        return known + e_same + void_weight * e_void

    def risk(self, card: Card, void_weight: float = 1.0) -> float:
        """0..1: P(wezmę) * oczekiwana kara, względem "złej lewy"."""
        if self.ref_penalty <= 0:
            return 0.0
        return min(1.0, self.p_win(card) * self.expected_trick_penalty(card, void_weight) / self.ref_penalty)


def prepare(state: GameState, params: Params) -> Ctx:
    n_players = state.num_players
    try:
        deck = full_deck(n_players)
        hand = [parse_card(c) for c in state.hand]
        history = [[parse_card(c) for c in t] for t in state.history]
        current = [parse_card(c) for c in state.current_trick]
        legal = None if state.legal_moves is None else [parse_card(c) for c in state.legal_moves]
    except ValueError as e:
        raise InvalidState(str(e)) from e

    n_tricks = total_tricks(n_players)
    if any(len(t) != n_players for t in history):
        raise InvalidState(f"Każda zakończona lewa musi mieć {n_players} karty.")
    if len(current) >= n_players:
        raise InvalidState("Bieżąca lewa ma już komplet kart.")
    if len(history) >= n_tricks:
        raise InvalidState(f"Runda ma tylko {n_tricks} lew.")
    known = hand + [c for t in history for c in t] + current
    if len(set(known)) != len(known):
        raise InvalidState("Ta sama karta występuje więcej niż raz.")
    deck_set = set(deck)
    if any(c not in deck_set for c in known):
        raise InvalidState(f"Karta spoza talii dla {n_players} graczy.")
    if len(hand) != n_tricks - len(history):
        raise InvalidState(
            f"Po {len(history)} lewach na ręce powinno być {n_tricks - len(history)} kart, "
            f"jest {len(hand)}."
        )
    if legal is not None and not set(legal) <= set(hand):
        raise InvalidState("Legalne ruchy muszą być kartami z ręki gracza.")

    rules = get_rules(state.contract, n_players)
    known_set = set(known)
    unseen = [c for c in deck if c not in known_set]
    played = {c for t in history for c in t}
    max_card_pen = max(rules.card_penalty(c) for c in deck if c not in played)
    trick_number = len(history) + 1
    return Ctx(
        hand=hand, current=current, unseen=unseen, rules=rules, params=params,
        trick_number=trick_number,
        n_remaining=n_players - len(current) - 1,
        ref_penalty=float(rules.trick_penalty(trick_number) + max_card_pen),
        total_tricks=n_tricks, legal=legal,
    )
