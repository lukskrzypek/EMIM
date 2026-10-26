"""Lobby-only dialog: the bots' memory files (``logs/memory_*.txt``) and deleting them."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from controllers.ai_bot import DEFAULT_MEMORY_DIR
from gui.core.log_cleanup import MemoryFile, delete_memory_file, list_memory_files
from gui.qt.theme import enable_wrapping


def _size(size: int) -> str:
    return f"{size} B" if size < 1024 else f"{size / 1024:.1f} KB"


class MemoryDialog(QDialog):
    """Pick memory files from the list and delete them (after a yes/no question).

    Opened from the lobby only: while a game runs the bots keep their memory in use.
    """

    def __init__(self, directory: Path = DEFAULT_MEMORY_DIR, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.directory = Path(directory)
        self.setWindowTitle("Pamięć botów")
        self.resize(560, 460)
        self._files: list[MemoryFile] = []

        intro = QLabel("Pliki pamięci botów. Zaznacz te, które chcesz usunąć.")
        intro.setWordWrap(True)
        self.listing = QListWidget()
        self.listing.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        enable_wrapping(self.listing)
        self.preview = QPlainTextEdit()
        self.preview.setReadOnly(True)
        self.preview.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)
        self.preview.setPlaceholderText("Zaznacz plik, żeby zobaczyć koniec jego pamięci")
        self.status = QLabel("")
        self.status.setObjectName("muted")
        self.status.setWordWrap(True)

        self.delete_button = QPushButton("Usuń zaznaczone")
        self.delete_button.setEnabled(False)
        self.close_button = QPushButton("Zamknij")
        buttons = QHBoxLayout()
        buttons.addWidget(self.delete_button)
        buttons.addStretch(1)
        buttons.addWidget(self.close_button)

        layout = QVBoxLayout(self)
        layout.addWidget(intro)
        layout.addWidget(self.listing, 2)
        layout.addWidget(self.preview, 1)
        layout.addWidget(self.status)
        layout.addLayout(buttons)

        self.listing.itemSelectionChanged.connect(self._on_selection)
        self.delete_button.clicked.connect(self._delete_selected)
        self.close_button.clicked.connect(self.accept)
        self.reload()

    # ------------------------------------------------------------------ list

    def reload(self) -> None:
        self._files = list_memory_files(self.directory)
        self.listing.clear()
        for file in self._files:
            item = QListWidgetItem(f"{file.bot}   ({_size(file.size)})")
            item.setToolTip(file.name)
            item.setData(Qt.ItemDataRole.UserRole, str(file.path))
            self.listing.addItem(item)
        if not self._files:
            self.status.setText("Brak plików pamięci.")
        self._on_selection()

    def selected_files(self) -> list[MemoryFile]:
        chosen = {item.data(Qt.ItemDataRole.UserRole) for item in self.listing.selectedItems()}
        return [file for file in self._files if str(file.path) in chosen]

    def _on_selection(self) -> None:
        chosen = self.selected_files()
        self.delete_button.setEnabled(bool(chosen))
        if len(chosen) == 1:
            self.preview.setPlainText(chosen[0].preview or "(pusta)")
        else:
            self.preview.clear()

    # ---------------------------------------------------------------- delete

    def _delete_selected(self) -> None:
        chosen = self.selected_files()
        if not chosen:
            return
        names = "\n".join(f"• {file.name}" for file in chosen)
        answer = QMessageBox.question(
            self,
            "Usuń pamięć",
            f"Usunąć pamięć ({len(chosen)}):\n{names}\n\nNie da się tego cofnąć.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        failed = [file.name for file in chosen if not delete_memory_file(file.path, self.directory)]
        self.reload()
        done = len(chosen) - len(failed)
        text = f"Usunięto: {done}"
        if failed:
            text += f" · nie udało się: {', '.join(failed)}"
        self.status.setText(text)
