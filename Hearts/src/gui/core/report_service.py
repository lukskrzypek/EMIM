"""Offline quality report of ``logs/trajectories.jsonl`` for the GUI (runs off the UI thread)."""

from __future__ import annotations

from collections.abc import Collection
from dataclasses import dataclass
from pathlib import Path

from evaluation.report import QualityReport, evaluate_log, format_report


@dataclass(frozen=True)
class ReportResult:
    path: Path
    ignored_models: tuple[str, ...]
    report: QualityReport | None = None
    text: str = ""  # ``format_report`` output: what the console report prints
    error: str | None = None


def parse_ignored(text: str) -> tuple[str, ...]:
    """``"human, smart_bot"`` -> ``("human", "smart_bot")``."""
    return tuple(dict.fromkeys(part.strip() for part in text.split(",") if part.strip()))


def load_report(path: str | Path, ignored_models: Collection[str] = ()) -> ReportResult:
    """Evaluate every logged move. Never raises: problems come back in ``error``."""
    path = Path(path)
    ignored = tuple(ignored_models)
    if not path.is_file():
        return ReportResult(path, ignored, error=f"Brak pliku logu: {path}")
    try:
        report = evaluate_log(path, ignored)
    except (OSError, UnicodeDecodeError) as exc:
        return ReportResult(path, ignored, error=f"Nie można odczytać logu: {exc}")
    return ReportResult(path, ignored, report=report, text=format_report(report))
