"""Picks the card deck: PNG files from ``assets/cards`` when present, otherwise the vector one."""

from __future__ import annotations

from pathlib import Path

from gui.config import CARDS_DIR
from gui.qt.table.card_renderer import CardRenderer
from gui.qt.table.pixmap_card_renderer import PixmapCardRenderer
from gui.qt.table.vector_card_renderer import VectorCardRenderer


def has_png_deck(directory: Path = CARDS_DIR) -> bool:
    """A folder counts as a deck as soon as it holds at least one card image or ``back.png``."""
    return directory.is_dir() and any(directory.glob("*.png"))


def default_renderer(directory: Path = CARDS_DIR) -> CardRenderer:
    """Missing PNG files are drawn by the vector renderer, so a partial deck is fine."""
    vector = VectorCardRenderer()
    if has_png_deck(directory):
        return PixmapCardRenderer(directory, fallback=vector)
    return vector
