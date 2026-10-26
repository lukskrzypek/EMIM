"""Wszystkie strojone liczby modelu w jednym miejscu.

Poprawność: każdy ruch startuje od 100 i traci punkty za odstępstwa od reguł.
Agresywność: skala 0-100, składana z kilku niezależnych składników.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Params:
    # --- model przeciwników ---
    overtake_rate: float = 0.7   # szansa, że przeciwnik, który MOŻE przebić moją kartę, to zrobi
    attack_rate: float = 0.7     # szansa, że przeciwnik ZRZUCI mi karnę kartę na lewę, którą biorę

    # --- "ktoś ma dużo danego koloru" ---
    heavy_fraction: float = 0.4  # "dużo" = co najmniej tyle ułamka ręki przeciwnika...
    heavy_min_cards: int = 3     # ...ale nie mniej niż tyle kart

    # --- poprawność: punkty odejmowane od 100 ---
    forced_rank_loss: float = 50.0          # wymuszone zebranie: strata przy najgorszej z kart (skala liniowa)
    forced_penalty_card_cap: float = 25.0   # wymuszone zebranie kartą punktową, gdy są niepunktowe: max wynik
    take_not_highest_loss: float = 30.0     # celowe zebranie niższą niż najwyższa niepunktowana (skala wg różnicy rang)
    dump_order_loss: float = 30.0           # zrzut mniejszej kary zamiast większej
    dump_rank_loss: float = 4.0             # przy równych karach: lepiej zrzucić wyższą kartę
    missed_dump_loss: float = 40.0          # niepunktowana karta, choć mogłem bezpiecznie zrzucić punktową
    shed_rank_loss: float = 20.0            # niższa karta niż najwyższa możliwa bez brania (skala wg różnicy rang)
    duck_missed_take_loss: float = 40.0     # dokładam pod spód, choć mogłem bezpiecznie zebrać czystą lewę
                                            # (maleje z ryzykiem tego zebrania i z numerem lewy)
    take_known_penalty_cap: float = 15.0    # max poprawność, gdy na pewno biorę znane kary, a mogłem nie brać
    suspect_bonus: float = 20.0             # bonus, gdy ktoś prawdopodobnie ma dużo koloru, którego się pozbywam
    lead_own_penalty_loss: float = 40.0     # wyjście w kolor z moimi kartami punktowanymi (są inne)
    lead_long_suit_loss: float = 5.0        # długi kolor, w którym punktowane mają inni (nadal poprawne)
    lead_no_danger_loss: float = 25.0       # długi kolor bez żadnych kar w grze ("nic nie daje")
    lead_last_card_relief: float = 0.5      # wyjście ostatnią kartą koloru: o tyle mniej liczy się ryzyko
                                            # zrzutu kar od gracza bez koloru (pozbywam się koloru)

    # --- agresywność ---
    take_aggr_base: float = 55.0       # zamiar zebrania lewy: wartość na początku rozdania...
    take_aggr_progress: float = 40.0   # ...plus tyle na końcu (rośnie liniowo z numerem lewy)
    void_aggr: float = 40.0            # ryzyko, że komuś skończy się kolor
    risk_aggr: float = 40.0            # ryzyko wzięcia kar
    dump_pen_aggr: float = 10.0        # zrzut karty punktowej na lewę, której nie wezmę
    shed_base_aggr: float = 15.0       # pozbywanie się karty niepunktowej: podstawa
    shed_high_aggr: float = 30.0       # ...plus tyle za wysoką kartę
    shed_kept_aggr: float = 50.0       # ...plus tyle za zatrzymanie kar, które mogłem zrzucić
