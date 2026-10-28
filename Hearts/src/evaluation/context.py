"""Stan gry, walidacja wejścia i obliczenia pomocnicze (prawdopodobieństwa, ryzyko)."""
from __future__ import annotations

import math
from dataclasses import dataclass, field

from .cards import Card, full_deck, parse_card, total_tricks
from .params import Params
from engine.contracts import GameContract, contract_total_penalty

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
    # wiedza o przeciwnikach z historii (miejsca liczone względem wychodzącego w 1. lewie)
    followers: list[int] = field(default_factory=list)       # miejsca graczy po mnie w tej lewie
    hand_sizes: dict[int, int] = field(default_factory=dict)  # miejsce przeciwnika -> liczba kart
    voids: dict[int, set[str]] = field(default_factory=dict)  # znane renonse (zagrał inny kolor)
    declined: dict[int, set[Card]] = field(default_factory=dict)  # mógł bezpiecznie dołożyć tę karę, nie zrobił
    contract_total: int = 0     # suma wszystkich kar rozdania (skala bezwzględnej wagi kary)

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
        # (z uwzględnieniem renonsów i "odmów" - patrz hold_prob)
        same = sum(self.p_comes(c) * self.pen(c) for c in self.unseen if c.suit == suit and self.pen(c) > 0)
        e_same = P.attack_rate * same
        # gracz bez koloru może zrzucić mi dowolną punktowaną kartę
        others = [self.pen(c) for c in self.unseen if c.suit != suit and self.pen(c) > 0]
        e_void = 0.0
        if others:
            mean_pen = sum(others) / len(others)
            p_has = min(1.0, self.h * len(others) / total)
            e_void = P.attack_rate * self.void_prob(suit) * p_has * mean_pen
        return known + e_same + void_weight * e_void

    # ---------- wiedza o przeciwnikach ----------
    def hold_prob(self, card: Card, seat: int) -> float:
        """P(niewidziana karta jest u przeciwnika na miejscu ``seat``) - z uwzględnieniem renonsów
        i "odmowy" dołożenia tej karty (mógł blefować, więc nie zero)."""
        def weight(s: int) -> float:
            if card.suit in self.voids.get(s, ()):
                return 0.0
            bluff = self.params.decline_bluff if card in self.declined.get(s, ()) else 1.0
            return self.hand_sizes[s] * bluff
        total = sum(weight(s) for s in self.hand_sizes)
        return weight(seat) / total if total > 0 else 0.0

    def p_comes(self, card: Card) -> float:
        """P(niewidziana karta jest u któregoś z graczy, którzy zagrają po mnie w tej lewie)."""
        return sum(self.hold_prob(card, s) for s in self.followers)

    def p_stuck(self, card: Card) -> float:
        """P(zostanę z lewą, gdy gracze po mnie chcą mi dorzucić karę - nikt nie przebija dobrowolnie).

        Przebić muszą tylko ci, którzy mają w kolorze same wyższe karty."""
        if not self.beats_current(card):
            return 0.0
        suit = self.lead_suit or card.suit
        fol = [s for s in self.followers if suit not in self.voids.get(s, ())]
        if not fol:
            return 1.0
        in_suit = [c for c in self.unseen if c.suit == suit]
        higher = [c for c in in_suit if c.value > card.value]
        if not higher:
            return 1.0
        n_hi = len(higher)
        per_player = len(in_suit) / len(fol)
        forced = (n_hi / len(in_suit)) ** max(0.0, per_player - 1)  # posiadacz wyższej nie ma niższej
        p = 1.0
        for c in higher:
            p *= 1 - forced * sum(self.hold_prob(c, s) for s in fol)
        return p

    def severity(self, points: float) -> float:
        """0..1: bezwzględna waga kary względem całej puli kar kontraktu (dama w "bez dam" = 1)."""
        P = self.params
        if points <= 0 or self.contract_total <= 0:
            return 0.0
        return min(1.0, points / (P.severe_share * self.contract_total)) ** P.severity_exp

    def danger_loss(self, card: Card, shed: bool = False) -> float:
        """0..1: strata za wystawienie się na dorzucenie kary, gdy biorę lewę.

        * pułapka - niewidziana karta punktowana tego koloru, niższa od mojej, może u graczy po mnie
          (np. król, gdy dama nie wyszła, w rundzie bez dam),
        * znany renons - gracz po mnie nie ma koloru (pokazał to wcześniej) i zrzuci mi karę.
        ``shed`` - pozbywam się koloru (ostatnia/przedostatnia karta): tania kara jest wtedy akceptowalna."""
        P = self.params
        if self.n_remaining == 0 or not self.beats_current(card):
            return 0.0
        suit = self.lead_suit or card.suit
        trap = [c for c in self.unseen if c.suit == suit and c.value < card.value and self.pen(c) > 0]
        e_trap = sum(self.p_comes(c) * self.pen(c) for c in trap)
        e_trap = min(e_trap, self.n_remaining * max((self.pen(c) for c in trap), default=0))
        off = sorted((c for c in self.unseen if c.suit != suit and self.pen(c) > 0),
                     key=lambda c: -self.pen(c))
        e_void, dumped = 0.0, list(trap)
        for s in self.followers:
            if suit not in self.voids.get(s, ()):
                continue
            dumped = trap + off
            none = 1.0  # oczekiwana najwyższa kara, jaką ten gracz ma do zrzucenia
            for c in off:
                hp = self.hold_prob(c, s)
                e_void += none * hp * self.pen(c)
                none *= 1 - hp
        sev = self.severity(e_trap + e_void)
        if sev == 0:
            return 0.0
        relief = 1.0
        if shed:  # pozbycie się koloru jest warte zapłaty tylko tanią karą (kier tak, dama nigdy)
            worst = max(self.pen(c) for c in dumped) / (P.severe_share * self.contract_total)
            relief = 1 - P.void_shed_relief * max(0.0, 1 - worst)
        return min(1.0, self.p_stuck(card) * P.dump_rate * sev * relief)

    def is_bait(self, card: Card) -> bool:
        """Wyjście najniższą pozostałą kartą koloru, którego jeden z graczy po mnie nie ma
        (znany renons), a ktoś inny go ma - lewę na pewno weźmie przeciwnik i to on dostanie zrzut."""
        if self.current or not any(card.suit in self.voids.get(s, ()) for s in self.followers):
            return False
        rest = [c for c in self.unseen if c.suit == card.suit]
        return bool(rest) and all(c.value > card.value for c in rest)

    def nothing_left(self) -> bool:
        """Nie ma już żadnej kary do wzięcia (karty ani lewy) - żaden ruch niczego nie psuje."""
        cards = self.hand + self.current + self.unseen
        return (all(self.pen(c) == 0 for c in cards)
                and all(self.rules.trick_penalty(t) == 0
                        for t in range(self.trick_number, self.total_tricks + 1)))

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
    me, voids, declined = _seat_knowledge(history, current, n_players, deck, rules)
    order = [(me + i) % n_players for i in range(1, n_players)]
    before = {(me - i) % n_players for i in range(1, len(current) + 1)}
    return Ctx(
        hand=hand, current=current, unseen=unseen, rules=rules, params=params,
        trick_number=trick_number,
        n_remaining=n_players - len(current) - 1,
        ref_penalty=float(rules.trick_penalty(trick_number) + max_card_pen),
        total_tricks=n_tricks, legal=legal,
        followers=order[:n_players - len(current) - 1],
        hand_sizes={s: len(hand) - (s in before) for s in order},
        voids={s: voids[s] for s in order}, declined={s: declined[s] for s in order},
        contract_total=contract_total_penalty(state.contract, n_players),
    )


def _seat_knowledge(history: list[list[Card]], current: list[Card], n: int, deck: list[Card],
                    rules: RoundRules) -> tuple[int, dict[int, set[str]], dict[int, set[Card]]]:
    """(moje miejsce, renonse, "odmowy") z kolejności kart; miejsce 0 wychodzi w 1. lewie,
    kolejną lewę otwiera zwycięzca poprzedniej."""
    voids: dict[int, set[str]] = {s: set() for s in range(n)}
    declined: dict[int, set[Card]] = {s: set() for s in range(n)}
    leader = 0
    for trick in [*history, current]:
        if not trick:
            break
        lead = trick[0].suit
        best = 0
        for i, c in enumerate(trick[1:], start=1):
            seat = (leader + i) % n
            if c.suit != lead:
                voids[seat].add(lead)
                continue
            top = trick[best]
            # pod wyższą kartę mógł bezpiecznie dołożyć większą karę tego koloru - nie zrobił tego
            declined[seat] |= {d for d in deck if d.suit == lead and d.value < top.value
                               and rules.card_penalty(d) > rules.card_penalty(c)}
            if c.value > top.value:
                best = i
        if len(trick) == n:
            leader = (leader + best) % n
    return (leader + len(current)) % n, voids, declined
