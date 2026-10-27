"""Lobby: choose the number of players, a controller per seat and the session options."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QComboBox,
    QFormLayout,
    QFrame,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from controllers.ai_bot import DEFAULT_MEMORY_DIR
from gui.config import PLAYER_COUNTS
from gui.core.lobby_state import DEFAULT_PLAYERS, LobbyState
from gui.core.model_catalog import load_all_models
from gui.core.seat_config import SeatKind, SessionConfig
from gui.qt.lobby.memory_dialog import MemoryDialog
from gui.qt.lobby.seat_row import SeatRow, model_key

MAX_SEATS = max(PLAYER_COUNTS)


class LobbyView(QWidget):
    startRequested = Signal(object)  # SessionConfig
    reportRequested = Signal()

    def __init__(
        self,
        parent: QWidget | None = None,
        *,
        models_paths: Mapping[str, Path] | None = None,
        memory_dir: Path = DEFAULT_MEMORY_DIR,
    ) -> None:
        """``models_paths`` maps a provider id to its model list file (default: ``<id>_models.txt``)."""
        super().__init__(parent)
        self._memory_dir = Path(memory_dir)
        self._models_paths = dict(models_paths or {})
        models = load_all_models(self._models_paths)

        title = QLabel("Kierki")
        title.setObjectName("title")
        subtitle = QLabel("Kierki polskie (King): wybierz graczy przy stole i rozpocznij partię (7 rozdań na gracza).")
        subtitle.setObjectName("subtitle")

        self.players = QComboBox()
        for n in PLAYER_COUNTS:
            self.players.addItem(f"{n} graczy", n)
        self.players.setCurrentIndex(PLAYER_COUNTS.index(DEFAULT_PLAYERS))

        self.rows: list[SeatRow] = []
        seats_box = QVBoxLayout()
        for i in range(MAX_SEATS):
            row = SeatRow(i, SeatKind.HUMAN if i == 0 else SeatKind.SMART, models)
            row.changed.connect(self._update_state)
            row.becameAI.connect(self._give_free_model)
            self.rows.append(row)
            seats_box.addWidget(row)

        options = QFormLayout()
        options.addRow("Liczba graczy", self.players)

        self.message = QLabel()
        self.message.setObjectName("warning")
        self.message.setWordWrap(True)
        self.start_button = QPushButton("Rozpocznij grę")
        self.start_button.setObjectName("primary")
        self.start_button.setMinimumHeight(38)
        self.start_button.clicked.connect(self._start)
        self.report_button = QPushButton("Raport jakości z logu")
        self.report_button.setToolTip("Oceń wszystkie ruchy zapisane w logs/trajectories.jsonl")
        self.report_button.clicked.connect(self.reportRequested)
        self.memory_button = QPushButton("Pamięć botów…")
        self.memory_button.setToolTip("Lista plików pamięci botów; można usunąć wybrane")
        self.memory_button.clicked.connect(self.open_memory_dialog)

        card = QFrame()
        card.setObjectName("card")
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(20, 20, 20, 20)
        card_layout.setSpacing(14)
        card_layout.addLayout(options)
        card_layout.addSpacing(6)
        card_layout.addLayout(seats_box)
        card_layout.addWidget(self.message)
        card_layout.addWidget(self.start_button)
        card_layout.addWidget(self.report_button)
        card_layout.addWidget(self.memory_button)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(40, 30, 40, 30)
        outer.addWidget(title)
        outer.addWidget(subtitle)
        outer.addSpacing(10)
        outer.addWidget(card)
        outer.addStretch(1)

        self.players.currentIndexChanged.connect(lambda _: self._update_state())
        self._update_state()

    @property
    def num_players(self) -> int:
        return int(self.players.currentData())

    def state(self) -> LobbyState:
        """Everything the user chose, for ``AppSettings`` (all seats, also hidden ones)."""
        return LobbyState(
            players=self.num_players,
            seats=tuple(row.config() for row in self.rows),
        )

    def apply_state(self, state: LobbyState) -> None:
        self.players.setCurrentIndex(PLAYER_COUNTS.index(state.players))
        for row, seat in zip(self.rows, state.seats, strict=False):
            row.apply(seat)
        self._update_state()

    def build_config(self) -> SessionConfig:
        n = self.num_players
        return SessionConfig(
            seats=tuple(row.config() for row in self.rows[:n]),
        )

    def open_memory_dialog(self) -> None:
        """Memory can be deleted here only: a running game keeps using its bots' memory."""
        MemoryDialog(self._memory_dir, self).exec()

    def refresh(self) -> None:
        """Re-read the model list and re-check seats (the API key file may exist by now)."""
        models = load_all_models(self._models_paths)
        for row in self.rows:
            row.set_models(models)
        for row in self.rows:
            row.refresh()

    def _update_state(self) -> None:
        n = self.num_players
        for i, row in enumerate(self.rows):
            row.setVisible(i < n)
        seated = self.rows[:n]
        problems = [p for row in seated if (p := row.problem())]
        problems += self._shared_memory_problems(seated)
        self.message.setText("\n".join(dict.fromkeys(problems)))
        self.start_button.setEnabled(not problems)

    def _memory_owners(self, rows: list[SeatRow]) -> dict[str, tuple[str, list[str]]]:
        """AI seats by memory file: ``key -> (display name, [player ids])``."""
        owners: dict[str, tuple[str, list[str]]] = {}
        for row in rows:
            if row.is_ai:
                seat = row.config()
                owners.setdefault(seat.memory_key.strip().casefold(), (seat.display_name, []))[1].append(
                    row.player_id
                )
        return owners

    def _taken_by_others(self, row: SeatRow) -> dict[str, str]:
        """``model_key -> player id`` of the models played on the other visible seats."""
        taken: dict[str, str] = {}
        for other in self.rows[: self.num_players]:
            if other is not row and other.is_ai:
                taken.setdefault(model_key(other.model_name), other.player_id)
        return taken

    def _shared_memory_problems(self, rows: list[SeatRow]) -> list[str]:
        """Two seats of one model and one name would write into the same memory file."""
        return [
            f"Miejsca {', '.join(pids)} mają wspólną pamięć ({shown}) – nadaj im różne nazwy "
            "(najwyżej jedno miejsce danego modelu może być bez nazwy)."
            for shown, pids in self._memory_owners(rows).values()
            if len(pids) > 1
        ]

    def _give_free_model(self, row: SeatRow) -> None:
        """A seat that has just become AI (or changed provider) starts on a model nobody else plays, if there is one."""
        taken = self._taken_by_others(row)
        if model_key(row.model_name) in taken:
            row.pick_free_model(taken)

    def _start(self) -> None:
        if self.start_button.isEnabled():
            self.startRequested.emit(self.build_config())
