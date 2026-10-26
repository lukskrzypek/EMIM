"""The Groq models a seat can choose from, read from a plain text file (one model per line)."""

from __future__ import annotations

from pathlib import Path

from controllers.groq_icl_bot import DEFAULT_MODEL
from gui.config import MODELS_PATH

FALLBACK_MODELS: tuple[str, ...] = (DEFAULT_MODEL, "openai/gpt-oss-20b", "openai/gpt-oss-120b")


def parse_models(text: str) -> tuple[str, ...]:
    """Model ids from file text: comments and blanks dropped, duplicates (any case) merged."""
    seen: dict[str, str] = {}
    for line in text.splitlines():
        name = line.split("#", 1)[0].strip()
        if name:
            seen.setdefault(name.casefold(), name)
    return tuple(seen.values())


def load_models(path: Path = MODELS_PATH) -> tuple[str, ...]:
    """Models from ``path``; the built-in list when the file is missing, unreadable or empty."""
    try:
        models = parse_models(path.read_text(encoding="utf-8-sig"))
    except OSError:
        return FALLBACK_MODELS
    return models or FALLBACK_MODELS
