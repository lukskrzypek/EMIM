# Hearts (Kierki)

Jedno rozdanie kierków (2–5 graczy): człowiek, bot heurystyczny (`SmartHeartsBot`) i bot LLM (`GroqICLBot`), w oknie albo w konsoli. Zasady są w `SPEC.md`. Silnik (`src/engine/`) nie czyta wejścia i niczego nie wypisuje.

## Szybki start

Polecenia wykonuj w folderze `Hearts`.

### Co pobrać

- **Python 3.12+** z [python.org](https://www.python.org/downloads/) (zaznacz „Add python.exe to PATH”). Okno wymaga Pythona z python.org, nie z MSYS2.
- **Biblioteki** (jednorazowo):

```powershell
python -m venv .venv-gui
.\.venv-gui\Scripts\python.exe -m pip install -r requirements-gui.txt
```

To `groq`, `PySide6`, `pytest` i `pytest-qt`. Sam `main.py` wystarczy z `pip install -r requirements.txt` (`groq`, `pytest`). Silnik i `SmartHeartsBot` działają bez tych pakietów.

- **Klucz Groq** — tylko dla `GroqICLBot`. Darmowe konto na [console.groq.com](https://console.groq.com/keys), klucz `gsk_...`.

### Jak uruchomić

```powershell
.\.venv-gui\Scripts\python.exe gui_main.py
.\.venv-gui\Scripts\python.exe main.py
```

W lobby wybierz graczy i kliknij „Rozpocznij grę”. Bez `groq_api_key.txt` bot Groq jest niedostępny, reszta działa. Testy: `.\.venv-gui\Scripts\python.exe -m pytest` (bez PySide6 i `pytest-qt` testy GUI są pomijane).

### Ustawienia

| Co | Gdzie |
|---|---|
| Klucz API | `groq_api_key.txt` — pierwsza niepusta linia (`gsk_...`), cudzysłowy na brzegach są obcinane. Plik jest w `.gitignore`. Zmienna `GROQ_API_KEY` nie jest czytana. |
| Modele w lobby | `groq_models.txt`, jeden identyfikator w linii (`#` pomija linię). Po zmianie wróć do lobby. |
| Wytyczne bota Groq | lobby, pole „wytyczne startowe”, do 100 znaków, najlepiej po angielsku. Puste = `USER_GUIDELINES` w `src/controllers/groq_icl_bot.py`. |
| Gracze, rozdania, tempo | lobby i ekran gry; zostają między uruchomieniami. |

Nadają się modele czatowe. `llama-prompt-guard` to klasyfikatory i nie zagrają. `404 model_not_found` znaczy, że klucz nie widzi modelu:

```powershell
.\.venv-gui\Scripts\python.exe check_models.py
```

## Konsola

`main.py` pyta o liczbę graczy (2–5) i kontroler na każdym miejscu. Z człowiekiem przy stole jest jedno rozdanie. Same boty: program pyta o liczbę partii (jedna wypisuje ręce i zagrania, wiele — wynik każdego rozdania i podsumowanie). `0` zamiast liczby graczy uruchamia ocenę z logu.

Każdy ruch trafia do `logs/trajectories.jsonl` (kontekst, legalne karty, karta, uzasadnienie). Pole `model` to id LLM, `human` albo `smart_bot`.

## Kontrolery

| Kontroler | Zachowanie |
|---|---|
| `HumanCLIController` | Czyści konsolę między turami. Indeks albo kod karty (`0` lub `2C`). |
| `SmartHeartsBot` | Heurystyki i 40 losowań niewidocznych rąk (`num_samples`). Karta o najniższej średniej karze. Bez sieci. |
| `GroqICLBot` | Jedno zapytanie do Groq na ruch, gdy legalnych kart jest więcej niż jedna. |

## GroqICLBot

Domyślny model: `openai/gpt-oss-120b`. Dla `gpt-oss` jest `reasoning_effort="low"` i ścisły JSON (`card` z listy legalnych, `reasoning`, `memory`). Pozostałe modele dostają zwykły tryb JSON; odpowiedź w bloku ` ```json ` też jest czytana. Gdy API odrzuci format (400) albo limit `max_tokens`, bot łagodzi wymaganie albo obniża limit (najwyżej dwa ponowienia na ruch) i zapamiętuje to na kolejne ruchy.

- Jedna legalna karta jest grana od razu.
- Błąd API, pusta odpowiedź albo karta spoza listy: pierwsza legalna karta. Odrzucenie przez API → `logs/groq_api_errors.jsonl`. Odpowiedź, która nie jest legalną kartą → `logs/groq_illegal_moves.jsonl`.
- Pełne zapytanie i surowa odpowiedź → `logs/groq_exchanges.jsonl` (bez klucza).
- Few-shot jest wyłączony (`num_examples=0`). Przykłady z `logs/trajectories.jsonl` dokładają się przez `num_examples` (ostatnie rekordy albo `example_selection="random"`). Do promptu wchodzą tylko rekordy z więcej niż jedną kartą legalną.

Pusty albo brakujący klucz kończy się `RuntimeError` przy pierwszym zapytaniu.

### Pamięć

Przy ruchu model dostaje `logs/memory_<model>.txt` (`/` i inne znaki niedozwolone w nazwie → `_`) i może nadpisać plik polem `memory`. `null` albo pusty string nic nie zmienia. Zapis i odczyt mają najwyżej 600 znaków. Wyłączenie: `memory_path=""`.

W oknie ten sam model może usiąść kilka razy. Każde miejsce poza jednym potrzebuje nazwy (do 10 znaków): plik to wtedy `logs/memory_<model>_<nazwa>.txt`, a w logu pole `model` ma postać `<model>_<nazwa>`, więc raport liczy je osobno.

## Ocena jakości

Konsola: `0` przy pytaniu o liczbę graczy. Okno: zakładka „Jakość” liczy ruch przed zagraniem; raport w lobby liczy cały `logs/trajectories.jsonl` (ten sam tekst co tryb `0`).

Dla każdego ruchu odtwarzany jest stan rozdania (kier = 1 pkt, dama pik = 13 pkt) i wychodzi poprawność oraz agresywność (0–100). Ruchy z jedną legalną kartą nie wchodzą do średnich. Pomijani gracze: `IGNORED_PLAYERS` na początku `main.py`, domyślnie `("human", "smart_bot")`. Raport używa domyślnych parametrów ewaluatora; parametry z okna obowiązują tylko w bieżącej sesji.

„Usuń statystyki bota” kasuje jego rekordy z logów Groq oraz całe rozdania z `trajectories.jsonl`, w których grał.

## Okno

- **Stół.** Same boty mają karty odkryte. Jeden człowiek widzi swoje; karty botów odkrywa przełącznik. Kilku ludzi (hot-seat): zasłona między turami, stół obraca się do gracza.
- **Tempo.** Pauza, krok, suwak (skrajnie w prawo = bez przerw), pauza po lewie. Boty liczą w osobnym wątku, licznik „myśli… X s” stoi na pauzie.
- **Jakość.** Ranking ze średnim czasem odpowiedzi bota, trend, ocena legalnych kart ostatniego ruchu. Opcjonalnie podpowiedź dla człowieka.
- **Bot.** Uzasadnienia, czasy, notatnik Groq.
- **Pamięć** (przycisk w lobby, niedostępny w trakcie partii): podgląd i usuwanie `logs/memory_*.txt`.

| Klawisz | Działanie |
|---|---|
| `Spacja` | pauza / wznów |
| `N` | jeden ruch w pauzie |
| `+` / `-` | szybciej / wolniej |
| `Ctrl+1` … `Ctrl+4` | Wyniki, Jakość, Bot, Log |
| `F11` | pełny ekran |

### Własna talia PNG

Domyślnie karty są wektorowe (opcjonalnie w 4 kolorach). Własne obrazki wrzuć do `assets/cards/`: `2C.png` … `AS.png` (ranga i kolor silnika, np. `TH.png` = 10♥) oraz `back.png`. Brakujące pliki są dorysowywane. Proporcje 7:10. Tryb 4-kolorowy działa tylko z talią wektorową.
