"""The models an AI seat can choose from, read from one plain text file per provider."""

from __future__ import annotations

from pathlib import Path

from controllers.ai_bot import DEFAULT_PROVIDER, PROVIDERS, get_provider

# Used when a provider's model file is missing, unreadable or empty.
FALLBACK_MODELS: dict[str, tuple[str, ...]] = {
    "groq": (PROVIDERS["groq"].default_model, "openai/gpt-oss-20b"),
    "openai": (PROVIDERS["openai"].default_model, "gpt-4o"),
}


def parse_models(text: str) -> tuple[str, ...]:
    """Model ids from file text: comments and blanks dropped, duplicates (any case) merged."""
    seen: dict[str, str] = {}
    for line in text.splitlines():
        name = line.split("#", 1)[0].strip()
        if name:
            seen.setdefault(name.casefold(), name)
    return tuple(seen.values())


def load_models(path: Path | None = None, provider: str = DEFAULT_PROVIDER) -> tuple[str, ...]:
    """Models from ``path`` (default: the provider's own file); the built-in list on any problem."""
    info = get_provider(provider)
    try:
        models = parse_models((path or info.models_path).read_text(encoding="utf-8-sig"))
    except OSError:
        return FALLBACK_MODELS[info.id]
    return models or FALLBACK_MODELS[info.id]


def load_all_models(paths: dict[str, Path] | None = None) -> dict[str, tuple[str, ...]]:
    """``provider id -> models``; ``paths`` overrides the model file of the providers it names."""
    paths = paths or {}
    return {pid: load_models(paths.get(pid), pid) for pid in PROVIDERS}
