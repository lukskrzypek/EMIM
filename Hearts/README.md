# Hearts (Kierki)

Silnik jednego rozdania kierków (2–5 graczy) i trzy kontrolery: człowiek w konsoli, bot heurystyczny z Monte Carlo oraz bot LLM (`GroqICLBot`). Zasady są w `SPEC.md`. Silnik (`src/engine/`) nie czyta wejścia i niczego nie wypisuje.

Wymagany Python 3.12+.

## Uruchomienie

STWÓRZ PLIK groq_api_key.txt bezpośrednio w folderze projektu i wklej do niego swój klucz

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python main.py
```

`main.py` pyta o liczbę graczy (2–5) i o kontroler przy każdym miejscu: człowiek, `SmartHeartsBot` albo `GroqICLBot`. Gdy przy stole jest człowiek, gra się jedno rozdanie. Gdy same boty, program pyta o liczbę partii: przy jednej wypisuje ręce i kolejne zagrania, przy wielu — wynik każdego rozdania i podsumowanie serii. Każdy ruch (kontekst, legalne karty, wybrana karta, uzasadnienie) dopisywany jest do `logs/trajectories.jsonl`.

`pytest` jest w `requirements.txt`. Pakiet `groq` jest potrzebny tylko wtedy, gdy ktoś przy stole jest `GroqICLBot`. Silnik, `SmartHeartsBot` i testy działają bez SDK i bez klucza.

```powershell
python -m pytest
```

## Kontrolery

| Kontroler | Zachowanie |
|---|---|
| `HumanCLIController` | Czyści konsolę między turami. Gracz podaje indeks albo kod karty (`0` lub `2C`). |
| `SmartHeartsBot` | Heurystyki plus 40 losowań niewidocznych rąk (`num_samples`). Wybiera kartę o najniższej średniej karze. Bez sieci. |
| `GroqICLBot` | Jedno zapytanie do Groq na ruch, gdy legalnych kart jest więcej niż jedna. |

## Klucz API Groq

Klucz bierze się z pliku `groq_api_key.txt` w katalogu projektu (plik jest w `.gitignore`). Liczy się pierwsza niepusta linia; cudzysłowy na brzegach są obcinane.

```text
gsk_...
```

Zmienna środowiskowa `GROQ_API_KEY` nie jest czytana. `GroqICLBot` zawsze przekazuje do SDK klucz z pliku (albo z argumentu `api_key=`). Brak pliku albo pusta treść kończy się `RuntimeError` w momencie pierwszego zapytania.

## `GroqICLBot`

Domyślny model to `openai/gpt-oss-120b`. Dla modeli `gpt-oss` ustawiane jest `reasoning_effort="low"`. Odpowiedź jest wymuszana schematem JSON: `card` musi być jedną z kart legalnych, plus `reasoning` i `memory`.

```python
from controllers.groq_icl_bot import GroqICLBot

bot = GroqICLBot("P1", trajectories_path="logs/trajectories.jsonl")
move = bot.select_move(observation)
```

- Jedna legalna karta jest grana od razu, bez zapytania.
- Błąd API, pusta odpowiedź albo karta spoza listy legalnych: bot gra pierwszą legalną kartę. Taki przypadek trafia do `logs/groq_illegal_moves.jsonl`.
- Few-shot jest wyłączony (`num_examples=0`). Żeby dołożyć przykłady z `logs/trajectories.jsonl`, podaj `num_examples` (ostatnie rekordy, albo losowe przez `example_selection="random"`). Do promptu wchodzą tylko rekordy z więcej niż jedną kartą legalną.
- Pełne zapytanie i surowa odpowiedź (`content`, `reasoning`) są dopisywane do `logs/groq_exchanges.jsonl`. Klucz API do tego pliku nie trafia.

### Notatnik (`memory`)

Przy każdym ruchu model dostaje treść pliku `logs/memory_<gracz>.txt` (np. `memory_P1.txt`) i może ją nadpisać polem `memory` w JSON. `null` albo pusty string zostawia plik bez zmian. Zapis jest obcinany do 600 znaków; przy odczycie też wraca co najwyżej tyle ostatnich znaków. Wyłączenie zapisu: `memory_path=""`.


## Ocena jakości botów

Przy pytaniu o liczbę graczy wpisz `0`: zamiast gry program liczy jakość ruchów z `logs/trajectories.jsonl` (nic nie jest liczone w trakcie gry). Każdy rekord logu ma pole `model` — id modelu LLM (`GroqICLBot.model`), `human` albo `smart_bot`. Starsze rekordy bez tego pola są liczone jako `unknown`.

Algorytm to port biblioteki „kierki” (`src/evaluation/`): dla każdego ruchu odtwarzany jest stan rozdania (pełna historia z kolejnych rekordów, 2–5 graczy, legalne ruchy z silnika, runda `hearts`: kier = 1 pkt, dama pik = 13 pkt) i wyliczana jest poprawność (0–100) oraz agresywność (0–100). Raport grupuje wyniki po modelu; ruchy wymuszone (jedna legalna karta) nie wchodzą do średnich.

Lista pomijanych graczy to `IGNORED_PLAYERS` na początku `main.py` (domyślnie `("human", "smart_bot")`). Zmień ją, żeby ocenić też człowieka lub bota heurystycznego.