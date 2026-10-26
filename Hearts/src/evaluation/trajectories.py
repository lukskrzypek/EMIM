"""Odczyt logu ``trajectories.jsonl`` i odtworzenie stanu gry przed każdym ruchem.

Log zawiera jeden rekord na ruch, w kolejności rozgrywania. Prompt w rekordzie ma
tylko ostatnie lewy, dlatego pełną historię rozdania odtwarzamy z kolejnych rekordów.
Rozdanie zaczyna rekord z pierwszą lewą i pustym stołem.
"""

from __future__ import annotations

import json
import re
from collections import Counter
from collections.abc import Collection
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .context import GameState
from .rounds import RoundType

UNKNOWN_MODEL = "unknown"  # starsze rekordy nie mają pola "model"

_HEADER_RE = re.compile(r"^HEARTS (\d)p \| You: (\w+) \| Trick (\d+)")


@dataclass(frozen=True)
class LoggedMove:
    line: int
    player_id: str
    model: str
    chosen: str
    state: GameState


@dataclass
class LoadResult:
    moves: list[LoggedMove] = field(default_factory=list)
    records: int = 0                                   # niepuste linie logu
    ignored: Counter[str] = field(default_factory=Counter)   # model -> liczba pominiętych ruchów
    skipped: Counter[str] = field(default_factory=Counter)   # powód -> liczba pominiętych rekordów


class _BadRecord(ValueError):
    pass


def _parse_prompt(prompt: str) -> tuple[int, int, list[str], list[tuple[str, str]]]:
    """(liczba graczy, numer lewy, ręka, karty na stole jako (gracz, karta))."""
    lines = prompt.splitlines()
    header = _HEADER_RE.match(lines[0]) if lines else None
    if header is None:
        raise _BadRecord("nieznany format promptu")
    hand_line = next((ln for ln in lines if ln.startswith("Hand:")), None)
    trick_line = next((ln for ln in lines if ln.startswith("Trick:")), None)
    if hand_line is None or trick_line is None:
        raise _BadRecord("brak ręki lub stołu w prompcie")
    hand_text = hand_line[len("Hand:"):].strip()
    trick_text = trick_line[len("Trick:"):].strip()
    hand = [] if hand_text == "-" else hand_text.split()
    current: list[tuple[str, str]] = []
    if trick_text != "(empty)":
        for item in trick_text.split():
            player, sep, card = item.partition(":")
            if not sep:
                raise _BadRecord("zły zapis stołu")
            current.append((player, card))
    return int(header.group(1)), int(header.group(3)), hand, current


def _model_of(record: dict[str, Any]) -> str:
    model = record.get("model")
    return model.strip() if isinstance(model, str) and model.strip() else UNKNOWN_MODEL


def load_moves(path: str | Path, ignored_models: Collection[str] = ()) -> LoadResult:
    """Wczytaj ruchy z logu. Ruchy modeli z ``ignored_models`` są liczone, ale nie zwracane."""
    skip_models = {name.casefold() for name in ignored_models}
    result = LoadResult()
    plays: list[tuple[str, str]] = []   # wszystkie karty bieżącego rozdania w kolejności
    broken = False                      # niespójne rozdanie: pomijamy do następnego rozdania
    with Path(path).open(encoding="utf-8") as handle:
        for line_no, raw in enumerate(handle, start=1):
            raw = raw.strip()
            if not raw:
                continue
            result.records += 1
            try:
                record = json.loads(raw)
                player_id = record["player_id"]
                chosen = record["chosen_move"]
                legal = record["legal_moves"]
                n_players, trick_no, hand, current = _parse_prompt(record["prompt_context"])
                if not isinstance(player_id, str) or not isinstance(chosen, str) or chosen not in legal:
                    raise _BadRecord("zły ruch w rekordzie")
            except (json.JSONDecodeError, KeyError, TypeError, _BadRecord) as exc:
                broken = True
                result.skipped[f"uszkodzony rekord ({type(exc).__name__})"] += 1
                continue

            if trick_no == 1 and not current:
                plays, broken = [], False
            elif broken:
                result.skipped["niespójne rozdanie"] += 1
                continue

            done = (trick_no - 1) * n_players
            if len(plays) != done + len(current) or plays[done:] != current:
                broken = True
                result.skipped["niespójne rozdanie"] += 1
                continue

            model = _model_of(record)
            if model.casefold() in skip_models:
                result.ignored[model] += 1
            else:
                history = [
                    [card for _, card in plays[i:i + n_players]] for i in range(0, done, n_players)
                ]
                state = GameState(
                    hand=hand,
                    round_type=RoundType.HEARTS,
                    history=history,
                    current_trick=[card for _, card in current],
                    num_players=n_players,
                    legal_moves=list(legal),
                )
                result.moves.append(LoggedMove(line_no, player_id, model, chosen, state))
            plays.append((player_id, chosen))
    return result
