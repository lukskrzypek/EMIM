"""Deleting one bot's records from the logs (report tab) and its memory files (lobby only).

Everything here is Qt-free. A bot is identified by the label the report shows: ``<model>`` for an
unnamed bot, ``<model>_<name>`` for a named one (the bot's own ``model_name``).
"""

from __future__ import annotations

import json
import os
import re
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from controllers.ai_bot import (
    DEFAULT_API_ERROR_LOG_PATH,
    DEFAULT_EXCHANGE_LOG_PATH,
    DEFAULT_ILLEGAL_LOG_PATH,
    DEFAULT_MEMORY_DIR,
)

MEMORY_PREFIX = "memory_"
MEMORY_SUFFIX = ".txt"
PREVIEW_CHARS = 300


# ------------------------------------------------------------------ log records


@dataclass(frozen=True)
class DeletedRecords:
    """How many records of one bot were removed from each log."""

    trajectories: int = 0  # the bot's own moves
    exchanges: int = 0
    illegal: int = 0
    api_errors: int = 0
    other_trajectories: int = 0  # moves of the other players of the same deals (see below)

    @property
    def total(self) -> int:
        return self.trajectories + self.exchanges + self.illegal + self.api_errors + self.other_trajectories


def _label_of_trajectory(record: dict) -> str | None:
    model = record.get("model")
    return model if isinstance(model, str) else None


def _label_of_ai_log(record: dict) -> str | None:
    model = record.get("model")
    if not isinstance(model, str):
        return None
    name = record.get("name")
    return f"{model}_{name}" if isinstance(name, str) and name else model


def _rewrite_without(path: Path, label: str, label_of: Callable[[dict], str | None]) -> int:
    """Drop the lines of ``label`` from a JSONL file; blank and unreadable lines stay untouched."""
    if not path.is_file():
        return 0
    kept: list[str] = []
    removed = 0
    with path.open("r", encoding="utf-8", newline="") as handle:
        for line in handle:
            try:
                record = json.loads(line)
            except ValueError:
                record = None
            if isinstance(record, dict) and label_of(record) == label:
                removed += 1
            else:
                kept.append(line)
    if removed:
        temp = path.with_name(path.name + ".tmp")
        with temp.open("w", encoding="utf-8", newline="") as handle:
            handle.writelines(kept)
        os.replace(temp, path)  # atomic: a crash never leaves a half-written log
    return removed


_DEAL_START = re.compile(r"Trick (\d+)")


def _starts_deal(record: dict) -> bool:
    """First trick with an empty table: the same rule the report's loader uses."""
    prompt = record.get("prompt_context")
    if not isinstance(prompt, str):
        return False
    lines = prompt.splitlines()
    header = _DEAL_START.search(lines[0]) if lines else None
    table = next((ln for ln in lines if ln.startswith("Trick:")), None)
    return header is not None and header.group(1) == "1" and table is not None and table[6:].strip() == "(empty)"


def _trajectory_plan(path: Path, label: str) -> tuple[list[str], set[int], int, int]:
    """(lines, indexes to drop, the bot's own moves, moves of the others in the same deals).

    The report rebuilds every deal from the moves of *all* its players and rejects a deal that has a
    hole. So taking one bot's moves out leaves the other players' moves of those deals useless;
    they are dropped with it and counted separately.
    """
    lines = path.read_text(encoding="utf-8").splitlines(keepends=True) if path.is_file() else []
    deal_of: list[int | None] = []  # deal number of every line (None: before the first deal / blank)
    records: list[dict | None] = []
    current: int | None = None
    deals = 0
    for line in lines:
        try:
            record = json.loads(line)
        except ValueError:
            record = None
        if not isinstance(record, dict):
            record = None
        if record is not None and _starts_deal(record):
            deals += 1
            current = deals
        records.append(record)
        deal_of.append(current if line.strip() else None)
    hit = {
        deal_of[i]
        for i, record in enumerate(records)
        if record is not None and deal_of[i] is not None and _label_of_trajectory(record) == label
    }
    drop: set[int] = set()
    own = others = 0
    for i, record in enumerate(records):
        if deal_of[i] in hit and deal_of[i] is not None:
            drop.add(i)
            if record is not None and _label_of_trajectory(record) == label:
                own += 1
            else:
                others += 1
    return lines, drop, own, others


def preview_bot_records(label: str, trajectories_path: str | Path) -> tuple[int, int]:
    """``(own moves, other players' moves of the same deals)`` a deletion of ``label`` would remove."""
    _, _, own, others = _trajectory_plan(Path(trajectories_path), label)
    return own, others


def _delete_trajectories(path: Path, label: str) -> tuple[int, int]:
    lines, drop, own, others = _trajectory_plan(path, label)
    if drop:
        temp = path.with_name(path.name + ".tmp")
        with temp.open("w", encoding="utf-8", newline="") as handle:
            handle.writelines(line for i, line in enumerate(lines) if i not in drop)
        os.replace(temp, path)
    return own, others


def delete_bot_records(
    label: str,
    trajectories_path: str | Path,
    exchange_path: str | Path | None = DEFAULT_EXCHANGE_LOG_PATH,
    illegal_path: str | Path | None = DEFAULT_ILLEGAL_LOG_PATH,
    api_error_path: str | Path | None = DEFAULT_API_ERROR_LOG_PATH,
) -> DeletedRecords:
    """Remove the bot ``label`` from the trajectory log and the AI logs.

    In the trajectory log its deals go away whole (see ``_trajectory_plan``); in the bot's own
    logs only its own records do.
    """
    if not label:
        return DeletedRecords()
    own, others = _delete_trajectories(Path(trajectories_path), label)
    return DeletedRecords(
        trajectories=own,
        other_trajectories=others,
        exchanges=_rewrite_without(Path(exchange_path), label, _label_of_ai_log) if exchange_path else 0,
        illegal=_rewrite_without(Path(illegal_path), label, _label_of_ai_log) if illegal_path else 0,
        api_errors=_rewrite_without(Path(api_error_path), label, _label_of_ai_log) if api_error_path else 0,
    )


# ------------------------------------------------------------------ memory files


@dataclass(frozen=True)
class MemoryFile:
    path: Path
    size: int  # bytes
    preview: str  # the last lines, for the dialog

    @property
    def name(self) -> str:
        return self.path.name

    @property
    def bot(self) -> str:
        """``memory_openai_gpt-oss-120b_bold.txt`` -> ``openai_gpt-oss-120b_bold``."""
        return self.path.name[len(MEMORY_PREFIX) : -len(MEMORY_SUFFIX)]


def _is_memory_file(path: Path) -> bool:
    name = path.name
    return (
        path.is_file()
        and name.startswith(MEMORY_PREFIX)
        and name.endswith(MEMORY_SUFFIX)
        and len(name) > len(MEMORY_PREFIX) + len(MEMORY_SUFFIX)
    )


def list_memory_files(directory: str | Path = DEFAULT_MEMORY_DIR) -> list[MemoryFile]:
    """The ``memory_*.txt`` files of the memory directory, by name."""
    folder = Path(directory)
    if not folder.is_dir():
        return []
    files: list[MemoryFile] = []
    for path in sorted(folder.glob(f"{MEMORY_PREFIX}*{MEMORY_SUFFIX}")):
        if not _is_memory_file(path):
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
            size = path.stat().st_size
        except OSError:
            continue
        files.append(MemoryFile(path, size, text.strip()[-PREVIEW_CHARS:]))
    return files


def delete_memory_file(path: str | Path, directory: str | Path = DEFAULT_MEMORY_DIR) -> bool:
    """Delete one memory file. Only ``memory_*.txt`` directly inside ``directory`` is ever touched."""
    target = Path(path)
    folder = Path(directory)
    try:
        inside = target.resolve().parent == folder.resolve()
    except OSError:
        return False
    if not inside or not _is_memory_file(target):
        return False
    try:
        target.unlink()
    except OSError:
        return False
    return True
