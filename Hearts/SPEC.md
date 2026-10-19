# Specyfikacja Silnika Gry w Kierki (Hearts) - ICL Ready

## 1. Reprezentacja Danych (Format pod In-Context Learning)
- Karty używają wyłącznie skróconej notacji 2-znakowej: Wartość (`2`-`9`, `T`, `J`, `Q`, `K`, `A`) + Kolor (`C` - Trefl, `D` - Karo, `S` - Pik, `H` - Kier). Przykłady: `2C`, `TD`, `QS`, `AH`.
- Starszeństwo kart od najniższej do najwyższej: `2, 3, 4, 5, 6, 7, 8, 9, T, J, Q, K, A`.

## 2. Warianty Liczby Graczy i Talia (Bez fazy przekazywania kart na start)
- 2 graczy: pełna talia 52 kart (po 26 na gracza).
- 3 graczy: z talii 52 kart usuwamy `2D` (51 kart, po 17 na gracza).
- 4 graczy: pełna talia 52 kart (po 13 na gracza).
- 5 graczy: z talii 52 kart usuwamy `2D` oraz `2S` (50 kart, po 10 na gracza).

## 3. Zasady Rozgrywki (Pojedyncze Rozdanie)
- Pierwszą lewę (Trick 1) rozpoczyna gracz posiadający `2C` i musi wyjść tą kartą.
- Obowiązek dokładania do koloru wyjścia (Leading Suit). Jeśli gracz nie ma koloru, może dorzucić dowolną kartę (z wyjątkiem ograniczeń pierwszej lewy).
- Ograniczenia pierwszej lewy: nie wolno dorzucić kart punktowanych (żadnych kierów `H` ani Damy Pik `QS`), chyba że gracz ma na ręce wyłącznie karty punktowane.
- Łamanie Kierów (`hearts_broken`): Nie można wyjść kierem jako pierwszą kartą w lewie, dopóki kiery nie zostaną "złamane" (ktoś zrzucił kiera w poprzednich lewach z braku koloru) LUB gracz ma na ręce wyłącznie kiery.
- Lewę bierze gracz, który zagrał najwyższą kartę w kolorze wyjścia, i on rozpoczyna kolejną lewę.

## 4. Punktacja (Koniec Rozdania)
- Każdy kier (`H`) = 1 punkt karny.
- Dama Pik (`QS`) = 13 punktów karnych.
- Suma punktów w rozdaniu = 26.
- Shooting the Moon: Jeśli jeden gracz zbierze wszystkie 26 punktów karnych, otrzymuje 0 punktów, a każdy z pozostałych graczy otrzymuje +26 punktów.

## 5. Obserwacja Gracza i Pamięć Stołu (Wymagania pod ICL)
Silnik musi udostępniać metodę `get_player_observation(player_id) -> PlayerObservation`, która zwraca:
- `player_id`: ID gracza (np. `P0`, `P1`).
- `hand`: posortowana lista kart na ręce gracza (np. `["2C", "KC", "8D", "QS"]`).
- `current_trick`: lista krotek `(player_id, card_str)` z obecnej lewy.
- `trick_history`: lista zwięzłych podsumowań zakończonych lew, np. `"T1: P0:2C, P1:9C, P2:AC, P3:4C -> Win:P2 (0pts)"`.
- `exposed_voids`: słownik pokazujący, którzy gracze ujawnili brak danego koloru (np. `{"P1": ["C"], "P2": []}`). Wyliczane automatycznie, gdy gracz nie dołoży do koloru wyjścia.
- `hearts_broken`: bool.
- `scores`: słownik z punktami w bieżącym rozdaniu.
- `legal_moves`: lista dozwolonych kart do zagrania w tym ruchu (np. `["2C", "KC"]`).
- Metodę `to_icl_prompt() -> str`: formatującą powyższe dane w jeden czytelny, maksymalnie zwięzły blok tekstu (max 15-20 linii), gotowy do wysłania w prompcie dla LLM-a lub wyświetlenia człowiekowi w konsoli.