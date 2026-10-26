"""Persistent user settings (``QSettings``): window, lobby choices and view preferences."""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import QByteArray, QSettings

from gui.config import IGNORED_PLAYERS
from gui.core.lobby_state import LobbyState

ORGANISATION = "EMIM"
APPLICATION = "Kierki"


@dataclass(frozen=True)
class ViewPrefs:
    four_color: bool = False
    reveal_bots: bool = False
    hints: bool = False
    live_eval: bool = True
    after_trick: bool = False
    delay: float | None = None  # seconds between bot moves; None = the default


class AppSettings:
    """Typed access to one ``QSettings`` store. Tests pass a store in a temp file."""

    def __init__(self, store: QSettings | None = None) -> None:
        self.store = store if store is not None else QSettings(ORGANISATION, APPLICATION)

    # ---------------------------------------------------------------- window

    def geometry(self) -> QByteArray | None:
        value = self.store.value("window/geometry")
        return value if isinstance(value, QByteArray) and not value.isEmpty() else None

    def save_geometry(self, geometry: QByteArray) -> None:
        self.store.setValue("window/geometry", geometry)

    # ----------------------------------------------------------------- lobby

    def lobby_state(self) -> LobbyState:
        value = self.store.value("lobby/state")
        return LobbyState.from_json(value if isinstance(value, str) else None)

    def save_lobby_state(self, state: LobbyState) -> None:
        self.store.setValue("lobby/state", state.to_json())

    # ------------------------------------------------------------------ view

    def view_prefs(self) -> ViewPrefs:
        s = self.store
        raw_delay = s.value("view/delay")
        try:
            delay = None if raw_delay is None else max(0.0, float(raw_delay))
        except (TypeError, ValueError):
            delay = None
        return ViewPrefs(
            four_color=s.value("view/four_color", False, type=bool),
            reveal_bots=s.value("view/reveal_bots", False, type=bool),
            hints=s.value("view/hints", False, type=bool),
            live_eval=s.value("view/live_eval", True, type=bool),
            after_trick=s.value("view/after_trick", False, type=bool),
            delay=delay,
        )

    def save_view_prefs(self, prefs: ViewPrefs) -> None:
        s = self.store
        s.setValue("view/four_color", prefs.four_color)
        s.setValue("view/reveal_bots", prefs.reveal_bots)
        s.setValue("view/hints", prefs.hints)
        s.setValue("view/live_eval", prefs.live_eval)
        s.setValue("view/after_trick", prefs.after_trick)
        if prefs.delay is not None:
            s.setValue("view/delay", prefs.delay)

    # ---------------------------------------------------------------- report

    def report_ignored(self) -> str:
        value = self.store.value("report/ignored")
        return value if isinstance(value, str) else ", ".join(IGNORED_PLAYERS)

    def save_report_ignored(self, text: str) -> None:
        self.store.setValue("report/ignored", text)
