# Kierki polskie (King)

Partia kierków polskich (Króla) dla 3 albo 4 graczy. Jedna gra to 7 rozdań, po jednym na każdy kontrakt, w stałej kolejności (3 graczy: talia bez 2C). W lobby wpisuje się, ile takich gier rozegrać. Wygrywa najmniejsza suma kar. Grają: człowiek, bot heurystyczny (`SmartHeartsBot`) i bot LLM (`AIBot`), w oknie albo w konsoli. Zasady są w `SPEC.md` (a ich źródło w `rules.md`). Silnik (`src/engine/`) nie czyta wejścia i niczego nie wypisuje.

## Szybki start

Polecenia wykonuj w folderze `Hearts`.

### Co pobrać

- **Python 3.12+** z [python.org](https://www.python.org/downloads/) (zaznacz „Add python.exe to PATH”). Okno wymaga Pythona z python.org, nie z MSYS2.
- **Biblioteki** (jednorazowo):

```powershell
python -m venv .venv-gui
.\.venv-gui\Scripts\python.exe -m pip install -r requirements-gui.txt
```

To `groq`, `openai`, `PySide6`, `pytest` i `pytest-qt`. Sam `main.py` wystarczy z `pip install -r requirements.txt` (`groq`, `openai`, `pytest`). Silnik i `SmartHeartsBot` działają bez tych pakietów.

- **Klucz API** — tylko dla `AIBot`, wystarczy jeden z dwóch dostawców: Groq (darmowe konto na [console.groq.com](https://console.groq.com/keys), klucz `gsk_...`) albo OpenAI ([platform.openai.com](https://platform.openai.com/api-keys), klucz `sk-...`). Przy stole mogą siedzieć boty z obu naraz.

### Jak uruchomić

```powershell
.\.venv-gui\Scripts\python.exe gui_main.py
.\.venv-gui\Scripts\python.exe main.py
```

W lobby wybierz graczy i kliknij „Rozpocznij grę”. Bez pliku z kluczem dostawcy bot tego dostawcy jest niedostępny, reszta działa. Testy: `.\.venv-gui\Scripts\python.exe -m pytest` (bez PySide6 i `pytest-qt` testy GUI są pomijane).

### Ustawienia

| Co | Gdzie |
|---|---|
| Klucz API | `groq_api_key.txt` albo `openai_api_key.txt` — pierwsza niepusta linia, cudzysłowy na brzegach są obcinane. Pliki są w `.gitignore`. Zmienne środowiskowe nie są czytane. |
| Modele w lobby | `groq_models.txt` i `openai_models.txt`, jeden identyfikator w linii (`#` pomija linię). Po zmianie wróć do lobby. |
| Wytyczne bota AI | lobby, pole „wytyczne startowe”, do 100 znaków, najlepiej po angielsku. Puste = `USER_GUIDELINES` w `src/controllers/ai_bot.py`. |
| Gracze, tempo | lobby i ekran gry; zostają między uruchomieniami. |

Nadają się modele czatowe. `llama-prompt-guard`, `whisper`, `tts` czy `dall-e` nie zagrają. `404 model_not_found` znaczy, że klucz nie widzi modelu:

```powershell
.\.venv-gui\Scripts\python.exe check_models.py groq
.\.venv-gui\Scripts\python.exe check_models.py openai
```

## Konsola

`main.py` pyta o liczbę graczy (3 albo 4) i kontroler na każdym miejscu (człowiek, `SmartHeartsBot`, `AIBot` z Groq albo z OpenAI). Z człowiekiem przy stole jest jedna gra (7 rozdań). Same boty: program pyta, ile gier zasymulować (każda to 7 rozdań; jedna wypisuje ręce i zagrania, wiele — wynik każdej gry i podsumowanie). `0` zamiast liczby graczy uruchamia ocenę z logu.

Każdy ruch trafia do `logs/trajectories.jsonl` (kontekst, legalne karty, karta, uzasadnienie). Pole `model` to id LLM, `human` albo `smart_bot`.

## Kontrolery

| Kontroler | Zachowanie |
|---|---|
| `HumanCLIController` | Czyści konsolę między turami. Indeks albo kod karty (`0` lub `2C`). |
| `SmartHeartsBot` | Heurystyki zależne od kontraktu i 40 losowań niewidocznych rąk (`num_samples`). Karta o najniższej średniej karze w rozdaniu. Bez sieci. |
| `AIBot` | Jedno zapytanie do API (Groq albo OpenAI) na ruch, gdy legalnych kart jest więcej niż jedna. |

## AIBot

Dostawca (`provider="groq"` lub `"openai"`) wybiera SDK, plik z kluczem i listę modeli. Domyślny model: `openai/gpt-oss-120b` (Groq) i `gpt-4o-mini` (OpenAI). Ścisły JSON (`card` z listy legalnych, `reasoning`, `memory`) dostają `gpt-oss` na Groq i modele OpenAI; reasoning models (`gpt-oss`, `o*`, `gpt-5*`) dostają `reasoning_effort="low"`. Pozostałe modele Groq dostają zwykły tryb JSON; odpowiedź w bloku ` ```json ` też jest czytana. OpenAI dostaje limit jako `max_completion_tokens`. Gdy API odrzuci format, `temperature`, `reasoning_effort` (400) albo limit tokenów, bot łagodzi wymaganie albo obniża limit (najwyżej pięć ponowień na ruch) i zapamiętuje to na kolejne ruchy.

- Jedna legalna karta jest grana od razu.
- Błąd API, pusta odpowiedź albo karta spoza listy: pierwsza legalna karta. Odrzucenie przez API → `logs/ai_api_errors.jsonl`. Odpowiedź, która nie jest legalną kartą → `logs/ai_illegal_moves.jsonl`.
- Pełne zapytanie i surowa odpowiedź → `logs/ai_exchanges.jsonl` (bez klucza).

Pusty albo brakujący klucz kończy się `RuntimeError` przy pierwszym zapytaniu.

### Pamięć

Przy ruchu model dostaje `logs/memory_<model>.txt` (`/` i inne znaki niedozwolone w nazwie → `_`) i może nadpisać plik polem `memory`. `null` albo pusty string nic nie zmienia. Zapis i odczyt mają najwyżej 600 znaków. Wyłączenie: `memory_path=""`.

W oknie ten sam model może usiąść kilka razy. Każde miejsce poza jednym potrzebuje nazwy (do 10 znaków): plik to wtedy `logs/memory_<model>_<nazwa>.txt`, a w logu pole `model` ma postać `<model>_<nazwa>`, więc raport liczy je osobno.

## Ocena jakości

Konsola: `0` przy pytaniu o liczbę graczy. Okno: zakładka „Jakość” liczy ruch przed zagraniem; raport w lobby liczy cały `logs/trajectories.jsonl` (ten sam tekst co tryb `0`).

Dla każdego ruchu odtwarzany jest stan rozdania (kary bieżącego kontraktu) i wychodzi poprawność oraz agresywność (0–100). Ruchy z jedną legalną kartą nie wchodzą do średnich. Pomijani gracze: `IGNORED_PLAYERS` na początku `main.py`, domyślnie `("human", "smart_bot")`. Raport używa domyślnych parametrów ewaluatora; parametry z okna obowiązują tylko w bieżącej sesji.

„Usuń statystyki bota” kasuje jego rekordy z logów AI oraz całe rozdania z `trajectories.jsonl`, w których grał.

## Okno

- **Stół.** Same boty mają karty odkryte. Jeden człowiek widzi swoje; karty botów odkrywa przełącznik. Kilku ludzi (hot-seat): zasłona między turami, stół obraca się do gracza.
- **Tempo.** Pauza, krok, suwak (skrajnie w prawo = bez przerw), pauza po lewie. Boty liczą w osobnym wątku, licznik „myśli… X s” stoi na pauzie.
- **Jakość.** Ranking ze średnim czasem odpowiedzi bota, trend, ocena legalnych kart ostatniego ruchu. Opcjonalnie podpowiedź dla człowieka.
- **Bot.** Uzasadnienia, czasy, notatnik AI.
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
