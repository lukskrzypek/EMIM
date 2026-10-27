# Specyfikacja Silnika Gry: Kierki Polskie (King / Barbu) - ICL Ready

Źródło: `rules.md` + decyzje właściciela projektu (sekcja 7). Ten dokument zastępuje dawną specyfikację klasycznych Kierek (jedno rozdanie, 26 pkt, "shooting the moon", start od `2C`, `hearts_broken`).

## 1. Struktura i parametry gry

- Liczba graczy: **3 lub 4** (`num_players`). Gracze mają id `P0`, `P1`, ... (w silniku mogą być liczone jako indeksy 0..N-1).
- Kierunek gry: **zgodnie z ruchem wskazówek zegara** = rosnące indeksy (`P0 -> P1 -> P2 -> P3 -> P0`). Dotyczy kolejności kart w lewie, kolejności deklarujących i rozdawania.
- Talia:
  - 4 graczy: pełna talia 52 kart, po **13** kart na gracza, **13 lew**.
  - 3 graczy: talia 52 kart **bez `2C`** (51 kart), po **17** kart na gracza, **17 lew**.
- Notacja karty (wszędzie: silnik, obserwacja, logi, GUI): 2 znaki, wartość `2`-`9`, `T`, `J`, `Q`, `K`, `A` + kolor `C` (trefl), `D` (karo), `S` (pik), `H` (kier). Przykłady: `2C`, `TD`, `QS`, `KH`. `T` = 10.
- Wartość liczbowa rangi (`Card.value`): `2..10`, `J=11`, `Q=12`, `K=13`, `A=14`.
- Starszeństwo w kolorze (od najsłabszej): `2 < 3 < 4 < 5 < 6 < 7 < 8 < 9 < T < J < Q < K < A`.
- Brak atutu, brak przekazywania kart, brak licytacji kart.
- `total_tricks` = liczba kart na gracza (13 dla 4 graczy, 17 dla 3 graczy). "Ostatnia lewa" to lewa o numerze `total_tricks`.

## 2. Cykl partii i kontrakty

### 2.1 Przebieg partii

- Partia składa się z **jednej gry albo kilku gier z rzędu**. Jedna gra to **7 rozdań**: każdy kontrakt dokładnie raz, w stałej kolejności:

  `NO_TRICKS -> NO_HEARTS -> NO_QUEENS -> NO_MEN -> NO_KING_OF_HEARTS -> NO_7TH_AND_LAST -> ROBBER`

- Liczbę gier wybiera się przed startem (lobby: „Liczba gier”; konsola, gdy grają same boty: pytanie o liczbę gier). Domyślnie 1.
- Deklarujący:
  - w pierwszym rozdaniu sesji **losowy** (z `seed`, deterministycznie),
  - w każdym następnym kolejny gracz zgodnie z ruchem wskazówek zegara, także między grami.
  - Dla rozdania o numerze `d` (od 0): `declarer = (first_declarer + d) % num_players`, `contract = CONTRACT_ORDER[d % 7]`.
- Sesja ma `games * 7` rozdań. Deklarujący **wychodzi w pierwszej lewie** rozdania (`lead_player = declarer`). W kolejnych lewach wychodzi zwycięzca poprzedniej.
- W każdym rozdaniu karty są tasowane od nowa (deterministycznie z `seed` i numeru rozdania).
- Wybór kontraktu przez deklarującego (zamiast stałej kolejności) jest poza zakresem tej wersji (sekcja 8).

### 2.2 Punktacja: kary dodatnie, wygrywa najmniej

Punkty karne są **dodatnie**. Gracz z **najmniejszą sumą** punktów wygrywa. Remisy są dozwolone (kilku zwycięzców).

| Kontrakt | Kara |
|---|---|
| `NO_TRICKS` (bez lew) | 20 pkt za każdą wziętą lewę |
| `NO_HEARTS` (bez kierów) | 20 pkt za każdą kartę w kolorze `H` we wziętej lewie |
| `NO_QUEENS` (bez dam) | 60 pkt za każdą wziętą damę (`Q`) |
| `NO_MEN` (bez panów) | 30 pkt za każdego wziętego króla (`K`) i waleta (`J`) |
| `NO_KING_OF_HEARTS` (bez króla kier) | 150 pkt za wzięcie `KH` |
| `NO_7TH_AND_LAST` (bez 7. i ostatniej) | 75 pkt za wzięcie lewy nr 7 oraz 75 pkt za wzięcie ostatniej lewy (nr `total_tricks`) |
| `ROBBER` (rozbójnik) | suma kar ze wszystkich sześciu powyższych reguł jednocześnie |

Uwagi:
- W `ROBBER` `KH` kosztuje łącznie **200 pkt** (20 jako kier + 30 jako król + 150 jako `KH`).
- W `ROBBER` lewa nr 7 i lewa ostatnia kosztują 20 + 75 = 95 pkt (kara za lewę + kara specjalna).
- Kara za lewę = suma kar za karty w lewie + kara za numer lewy (dla kontraktów, które go mają).
- **Faza dodatnia (rozpaty / +25 za lewę): poza zakresem.**

### 2.3 Sumy kontrolne (niezmienniki do testów)

Suma kar wszystkich graczy w jednym rozdaniu jest stała dla kontraktu i liczby graczy:

| Kontrakt | 4 graczy (13 lew) | 3 graczy (17 lew) |
|---|---|---|
| `NO_TRICKS` | 260 | 340 |
| `NO_HEARTS` | 260 | 260 |
| `NO_QUEENS` | 240 | 240 |
| `NO_MEN` | 240 | 240 |
| `NO_KING_OF_HEARTS` | 150 | 150 |
| `NO_7TH_AND_LAST` | 150 | 150 |
| `ROBBER` | 1300 | 1380 |

(`2C` jest usuwana w grze 3-osobowej, ale nie jest ani kierem, ani damą, ani panem, więc kary kartowe się nie zmieniają. Zmienia się tylko liczba lew.)

Suma `total_scores` po całej partii = suma powyższych sum po wszystkich rozdaniach.

## 3. Zasady zagrywania kart (legal moves)

W każdej lewie:

1. **Wyjście (lead):** gracz rozpoczynający lewę może zagrać dowolną kartę z ręki, z jednym wyjątkiem:
   - W kontraktach **`NO_HEARTS`, `NO_KING_OF_HEARTS` i `ROBBER`** nie wolno wyjść w kiera (`H`), dopóki gracz ma na ręce karty w innych kolorach. Wyjątki (wtedy wolno wyjść w kiera): `KH` została już zagrana w bieżącym rozdaniu (w lewie zakończonej albo leżącej na stole) albo gracz ma na ręce wyłącznie kiery.
   - W pozostałych kontraktach (`NO_TRICKS`, `NO_QUEENS`, `NO_MEN`, `NO_7TH_AND_LAST`) wyjście jest w pełni dowolne.
2. **Dokładanie do koloru:** pozostali gracze **muszą** dołożyć kartę w kolorze wyjścia, jeśli ją mają. Jeśli nie mają, mogą zagrać **dowolną** kartę. Brak obowiązku bicia, brak atutu.
3. **Rozstrzygnięcie lewy:** lewę bierze gracz z najwyższą kartą w kolorze wyjścia. Zbiera karty i wychodzi jako pierwszy w następnej lewie.
4. Brak innych ograniczeń: brak `hearts_broken`, brak obowiązku startu `2C`, brak ograniczeń pierwszej lewy.
5. Rozdanie kończy się po rozegraniu wszystkich lew (`total_tricks`).

## 4. Deterministyczna maszyna stanów (GameState)

Silnik (`src/engine/`) jest czystym obiektem stanu: **zero I/O** (`print`, `input`, pliki, sieć). Ten sam `seed` (albo te same `hands`) i ta sama lista ruchów dają ten sam wynik.

```python
class GameContract(Enum):
    NO_TRICKS = "NO_TRICKS"
    NO_HEARTS = "NO_HEARTS"
    NO_QUEENS = "NO_QUEENS"
    NO_MEN = "NO_MEN"
    NO_KING_OF_HEARTS = "NO_KING_OF_HEARTS"
    NO_7TH_AND_LAST = "NO_7TH_AND_LAST"
    ROBBER = "ROBBER"

class Card:               # niezmienna (frozen), porównywalna, hashowalna
    suit: Suit            # 'C', 'D', 'S', 'H'
    rank: Rank            # 2..A
    value: int            # 2..14 (11=J, 12=Q, 13=K, 14=A)
    # parse("TD"), str(card) -> "TD"

class GameState:
    num_players: int                        # 3 lub 4
    total_deals: int                        # games * 7
    deal_number: int                        # 1..total_deals
    current_contract: GameContract
    declarer: str                           # deklarujący bieżące rozdanie
    hands: dict[str, list[Card]]            # ręce graczy
    current_trick: list[tuple[str, Card]]   # [(player_id, card), ...] w kolejności zagrania
    trick_number: int                       # 1..total_tricks
    scores: dict[str, int]                  # kary w bieżącym rozdaniu (dodatnie)
    total_scores: dict[str, int]            # suma kar w całej partii (dodatnie)
    lead_player: str                        # gracz rozpoczynający bieżącą lewę
    current_player: str | None              # gracz na ruchu; None gdy partia skończona

    def get_legal_moves(self, player_id: str) -> list[Card]: ...
    def play_card(self, player_id: str, card: Card) -> PlayResult: ...
    def evaluate_trick_penalty(self, trick_cards: list[Card], trick_num: int,
                               contract: GameContract) -> int: ...
    def clone(self) -> "GameState": ...      # niezależna kopia (do symulacji botów)
```

Wymagania:
- `get_legal_moves(player_id)`: lista legalnych kart zgodnie z sekcją 3; pusta, gdy gracz nie jest na ruchu albo rozdanie/partia się skończyły.
- `play_card(...)`: waliduje (kolejność, posiadanie karty, legalność; błąd `IllegalMoveError`), dokłada kartę, a przy ostatniej karcie lewy ją rozstrzyga, nalicza kary do `scores`, ustawia `lead_player`. Po ostatniej lewie rozdania dodaje `scores` do `total_scores` i (jeśli to nie ostatnie rozdanie) przechodzi do następnego rozdania (nowe rozdanie, kontrakt, deklarujący, `trick_number = 1`). Zwraca `PlayResult`: `player_id`, `card`, `trick_completed`, `trick_winner`, `trick_points`, `deal_over`, `game_over`.
- `evaluate_trick_penalty(trick_cards, trick_num, contract)`: czysta funkcja; zwraca **dodatnią** sumę kar za jedną lewę (karty + numer lewy) w danym kontrakcie. Numer ostatniej lewy zależy od liczby graczy (`total_tricks` stanu).
- Karty w lewie nie mogą się powtarzać, w całej talii żadna karta nie występuje dwa razy; liczba kart w rękach zgadza się z numerem lewy.
- Po zakończeniu partii: `winners` = gracze z najmniejszym `total_scores` (może być więcej niż jeden).
- Reguły (legalność, zwycięzca lewy, kary) są zdefiniowane **w jednym miejscu** (silnik). Boty i moduł oceny korzystają z nich (i z `clone()`), a nie mają własnych kopii zasad.

## 5. Obserwacja gracza i pamięć stołu (wymagania pod ICL)

Silnik udostępnia `get_player_observation(player_id) -> PlayerObservation` z polami:

- `player_id`, `num_players`, `current_player`.
- `contract` i `declarer`, `deal_number`, `total_deals`.
- `trick_number`, `total_tricks`.
- `hand`: posortowana lista kart gracza (np. `["2C", "KC", "8D", "QS"]`).
- `current_trick`: lista `(player_id, card_str)` bieżącej lewy.
- `trick_history`: zwięzłe podsumowania zakończonych lew bieżącego rozdania, np. `"T1: P0:2C, P1:9C, P2:AC, P3:4C -> Win:P2 (20pts)"` (punkty dodatnie).
- `played_cards`: strukturalna lista zagranych kart rozdania (kolejność gry), żeby boty nie parsowały tekstu.
- `exposed_voids`: kto ujawnił brak koloru, np. `{"P1": ["C"], "P2": []}`. Wyliczane, gdy gracz nie dołoży do koloru wyjścia.
- `scores`: kary w bieżącym rozdaniu; `total_scores`: kary w partii.
- `legal_moves`: lista legalnych kart na ten ruch.
- `game_over`.

`to_icl_prompt() -> str`: zwięzły blok tekstu (**max 15-20 linii**), dla LLM-a albo człowieka w konsoli. Zawiera nagłówek z kontraktem i deklarującym (np. `KING 4p | You: P1 | Deal 5/28 NO_HEARTS (declarer P0) | Trick 3/13 | Turn: P1`), jednolinijkowy opis kary kontraktu, rękę, bieżącą lewę, legalne ruchy, renonsy, punkty rozdania i partii oraz historię lew (z limitem). Nie zawiera pojęcia `hearts_broken`.

## 6. Kryteria poprawności (testy akceptacyjne)

- Wszystkie 7 kontraktów: kary kartowe i numerowe zgodnie z tabelą 2.2, sumy kontrolne 2.3 dla 3 i 4 graczy.
- Ograniczenie wyjścia w kiera działa w `NO_HEARTS`, `NO_KING_OF_HEARTS`, `ROBBER`, a w pozostałych kontraktach nie działa; wyjątki: `KH` już zagrana albo same kiery na ręce.
- Obowiązek dokładania do koloru, swobodny zrzut przy braku koloru, zwycięzca lewy = najwyższa karta w kolorze wyjścia.
- Talia: 4 graczy 52 karty (13 każdy), 3 graczy 51 kart bez `2C` (17 każdy); brak duplikatów.
- Harmonogram: `num_players * 7` rozdań, każdy gracz deklaruje każdy kontrakt raz, deklarujący zgodnie z ruchem wskazówek od losowego.
- Determinizm: ten sam `seed` i te same ruchy dają ten sam przebieg i wyniki; `clone()` jest niezależne od oryginału.
- Losowe pełne partie (legalne ruchy, 3 i 4 graczy) kończą się bez wyjątków, z zachowaniem niezmienników sum.
- Zwycięzca = najmniejszy `total_scores` (remisy dozwolone).

## 7. Decyzje projektowe (rozstrzygnięcia luk w `rules.md`)

1. Kontrakty w stałej kolejności (sekcja 2.1); wybór kontraktu przez gracza jest rozszerzeniem na później.
2. Pierwszy deklarujący jest losowy, kolejni zgodnie z ruchem wskazówek zegara. Deklarujący wychodzi w pierwszej lewie rozdania (decyzja uzupełniająca).
3. Ograniczenie wyjścia w kiera obowiązuje w `NO_KING_OF_HEARTS`, `NO_HEARTS` i `ROBBER`.
4. Punkty są dodatnie, wygrywa najmniejsza suma.
5. `KH` w `ROBBER` = 200 pkt.
6. Gra na 3 graczy (bez `2C`, 17 lew) i 4 graczy (13 lew). Warianty 2 i 5 graczy zostają usunięte.
7. Bez fazy dodatniej.
8. Notacja kart bez zmian (`T` = 10); `Card.value` 2..14.
9. Wygrywa najmniejszy wynik, remisy dozwolone.
10. Identyfikatory graczy zostają stringami `P0`.. na granicy silnika (GUI, logi, boty).

## 8. Poza zakresem tej wersji

- Faza gier dodatnich (+25 za lewę, rozpaty).
- Wybór kontraktu przez deklarującego.
- Przekazywanie kart, warianty 2 i 5 graczy.
- Zgodność ze starymi logami (`logs/trajectories.jsonl` w formacie `HEARTS ...`): stary format nie jest obsługiwany.
