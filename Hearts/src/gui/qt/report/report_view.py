"""Report tab: quality of every move ever logged, computed on a worker thread."""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

from PySide6.QtCore import QObject, QRunnable, Qt, QThreadPool, Signal
from PySide6.QtGui import QColor, QFontDatabase, QGuiApplication
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from evaluation.report import VERDICTS, ModelQuality
from gui.core.log_cleanup import delete_bot_records, preview_bot_records
from gui.core.report_service import ReportResult, load_report, parse_ignored
from gui.qt.quality.quality_panel import SCENARIO_NAMES
from gui.qt.quality.widgets import BarList, BarRow, GaugeWidget, VerdictBar, correctness_color
from gui.qt.settings import AppSettings
from gui.qt.theme import TEXT

COLUMNS = ("Model", "Ruchy", "Wybory", "Poprawn.", "Agres.")


class _Signals(QObject):
    done = Signal(int, object)  # request id, ReportResult


class _ReportJob(QRunnable):
    def __init__(self, request: int, path: Path, ignored: tuple[str, ...], signals: _Signals) -> None:
        super().__init__()
        self.request, self.path, self.ignored, self.signals = request, path, ignored, signals

    def run(self) -> None:
        result = load_report(self.path, self.ignored)
        try:
            self.signals.done.emit(self.request, result)
        except RuntimeError:  # the view was closed while the log was being evaluated
            pass


def _fmt(value: float | None) -> str:
    return "–" if value is None else f"{value:.1f}"


class ReportView(QWidget):
    backRequested = Signal()
    finished = Signal()  # a result (or an error) has been shown

    def __init__(
        self,
        log_path: Path,
        *,
        ignored_default: tuple[str, ...] = (),
        settings: AppSettings | None = None,
        exchange_path: Path | None = None,
        illegal_path: Path | None = None,
        api_error_path: Path | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.log_path = Path(log_path)
        # the bot's own logs live next to the trajectory log
        self.exchange_path = Path(exchange_path or self.log_path.with_name("groq_exchanges.jsonl"))
        self.illegal_path = Path(illegal_path or self.log_path.with_name("groq_illegal_moves.jsonl"))
        self.api_error_path = Path(api_error_path or self.log_path.with_name("groq_api_errors.jsonl"))
        self.settings = settings
        self.result: ReportResult | None = None
        self._ranked: list[ModelQuality] = []
        self._summary = ""
        self._note = ""  # shown after the next result, e.g. what a deletion removed
        self._request = 0
        self._signals = _Signals(self)
        self._signals.done.connect(self._on_done)

        title = QLabel("Raport jakości z logu")
        title.setObjectName("title")
        self.path_label = QLabel(str(self.log_path))
        self.path_label.setObjectName("muted")
        self.ignored = QLineEdit(
            settings.report_ignored() if settings is not None else ", ".join(ignored_default)
        )
        self.ignored.setPlaceholderText("modele do pominięcia, po przecinku")
        self.ignored.setToolTip("Ruchy tych kontrolerów nie wchodzą do raportu (np. human, smart_bot)")
        self.refresh_button = QPushButton("Odśwież")
        self.refresh_button.setObjectName("primary")
        self.copy_button = QPushButton("Kopiuj jako tekst")
        self.copy_button.setEnabled(False)
        self.delete_button = QPushButton("Usuń statystyki bota")
        self.delete_button.setToolTip(
            "Usuwa z logów rekordy zaznaczonego bota (trajectories, groq_exchanges, "
            "groq_illegal_moves, groq_api_errors) razem z pozostałymi ruchami z jego rozdań. Nie da się tego cofnąć."
        )
        self.delete_button.setEnabled(False)
        self.back_button = QPushButton("Wróć do lobby")
        self.status = QLabel("")
        self.status.setObjectName("subtitle")
        self.status.setWordWrap(True)

        top = QHBoxLayout()
        top.addWidget(QLabel("Pomiń:"))
        top.addWidget(self.ignored, 1)
        top.addWidget(self.refresh_button)
        top.addWidget(self.copy_button)
        top.addWidget(self.delete_button)
        top.addWidget(self.back_button)

        # ---- summary tab
        self.table = QTableWidget(0, len(COLUMNS))
        self.table.setHorizontalHeaderLabels(COLUMNS)
        self.table.verticalHeader().hide()
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.table.itemSelectionChanged.connect(self._on_selection)

        self.detail_title = QLabel("")
        self.detail_title.setStyleSheet("font-size: 16px; font-weight: 600;")
        self.detail_title.setWordWrap(True)
        self.correctness_gauge = GaugeWidget("Poprawność")
        self.aggressiveness_gauge = GaugeWidget("Agresywność", graded=False)
        self.detail_stats = QLabel("")
        self.detail_stats.setObjectName("muted")
        self.detail_stats.setWordWrap(True)
        self.verdicts = VerdictBar()
        self.scenarios = BarList(label_width=140, empty_text="brak ocenionych ruchów")

        detail = QFrame()
        detail.setObjectName("card")
        dl = QVBoxLayout(detail)
        dl.setContentsMargins(14, 12, 14, 14)
        dl.addWidget(self.detail_title)
        gauges = QHBoxLayout()
        gauges.addWidget(self.correctness_gauge)
        gauges.addWidget(self.aggressiveness_gauge)
        dl.addLayout(gauges)
        dl.addWidget(self.detail_stats)
        dl.addWidget(self._muted("Werdykty"))
        dl.addWidget(self.verdicts)
        dl.addWidget(self._muted("Według scenariusza"))
        dl.addWidget(self.scenarios)
        dl.addStretch(1)
        detail_scroll = QScrollArea()
        detail_scroll.setWidgetResizable(True)
        detail_scroll.setFrameShape(QFrame.Shape.NoFrame)
        detail_scroll.setWidget(detail)

        splitter = QSplitter()
        splitter.addWidget(self.table)
        splitter.addWidget(detail_scroll)
        splitter.setStretchFactor(0, 2)
        splitter.setStretchFactor(1, 3)
        splitter.setSizes([420, 560])

        self.text = QPlainTextEdit()
        self.text.setReadOnly(True)
        self.text.setFont(QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont))
        self.text.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)

        self.tabs = QTabWidget()
        self.tabs.addTab(splitter, "Podsumowanie")
        self.tabs.addTab(self.text, "Tekst (jak w konsoli)")

        root = QVBoxLayout(self)
        root.setContentsMargins(24, 18, 24, 18)
        root.setSpacing(8)
        root.addWidget(title)
        root.addWidget(self.path_label)
        root.addLayout(top)
        root.addWidget(self.status)
        root.addWidget(self.tabs, 1)

        self.refresh_button.clicked.connect(self.refresh)
        self.ignored.returnPressed.connect(self.refresh)
        self.copy_button.clicked.connect(self._copy)
        self.delete_button.clicked.connect(self._delete_selected)
        self.back_button.clicked.connect(self.backRequested)

    @staticmethod
    def _muted(text: str) -> QLabel:
        label = QLabel(text)
        label.setObjectName("muted")
        return label

    # ----------------------------------------------------------------- worker

    def refresh(self) -> None:
        """Evaluate the log on a pool thread; the UI stays usable meanwhile."""
        self._request += 1
        ignored = parse_ignored(self.ignored.text())
        if self.settings is not None:
            self.settings.save_report_ignored(self.ignored.text())
        self.refresh_button.setEnabled(False)
        self.status.setText("Liczenie ocen…")
        QThreadPool.globalInstance().start(
            _ReportJob(self._request, self.log_path, ignored, self._signals)
        )

    def _on_done(self, request: int, result: ReportResult) -> None:
        if request != self._request:  # a newer refresh is on its way
            return
        self.result = result
        self.refresh_button.setEnabled(True)
        self.copy_button.setEnabled(result.report is not None)
        if result.report is None:
            self.status.setText(f"⚠ {result.error}" + (f" · {self._note}" if self._note else ""))
            self._note = ""
            self.table.setRowCount(0)
            self.text.setPlainText(result.error or "")
            self._show_model(None)
            self.finished.emit()
            return
        report = result.report
        parts = [f"Rekordów w logu: {report.records}"]
        ignored = sum(report.ignored.values())
        if ignored:
            parts.append(f"pominięto {ignored} ruchów ({', '.join(report.ignored)})")
        for reason, count in sorted(report.skipped.items()):
            parts.append(f"odrzucono {count}: {reason}")
        self._summary = " · ".join(parts)
        note, self._note = self._note, ""
        self.status.setText(f"{self._summary} · {note}" if note else self._summary)
        self.text.setPlainText(result.text)
        self._fill_table(report.models.values())
        self.finished.emit()

    # ------------------------------------------------------------------ views

    def _fill_table(self, models: Iterable[ModelQuality]) -> None:
        ranked = sorted(
            models, key=lambda m: (-(m.correctness if m.correctness is not None else -1.0), m.model)
        )
        self._ranked = ranked
        self.table.setRowCount(len(ranked))
        for row, m in enumerate(ranked):
            cells = (m.model, str(m.moves), str(m.decisions), _fmt(m.correctness), _fmt(m.aggressiveness))
            for col, text in enumerate(cells):
                item = QTableWidgetItem(text)
                if col:
                    item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                if col == 3 and m.correctness is not None:
                    item.setForeground(QColor(correctness_color(m.correctness)))
                else:
                    item.setForeground(QColor(TEXT))
                self.table.setItem(row, col, item)
        if ranked:
            self.table.selectRow(0)
        else:
            self._show_model(None)

    def _on_selection(self) -> None:
        rows = self.table.selectionModel().selectedRows()
        index = rows[0].row() if rows else -1
        selected = self._ranked[index] if 0 <= index < len(self._ranked) else None
        self.delete_button.setEnabled(selected is not None)
        self._show_model(selected)

    def selected_label(self) -> str | None:
        rows = self.table.selectionModel().selectedRows()
        index = rows[0].row() if rows else -1
        return self._ranked[index].model if 0 <= index < len(self._ranked) else None

    def _delete_selected(self) -> None:
        """Remove the selected bot's records from the logs, after a yes/no question."""
        label = self.selected_label()
        if label is None:
            return
        try:
            own, others = preview_bot_records(label, self.log_path)
        except (OSError, UnicodeDecodeError) as exc:
            self.status.setText(f"⚠ Nie można odczytać logu: {exc}")
            return
        text = f"Usunąć z logów wszystkie rekordy bota „{label}”?\n\nRuchy bota: {own}."
        if others:
            text += (
                f"\nRaport ocenia rozdanie tylko w całości, więc razem z nimi znikną też ruchy "
                f"pozostałych graczy z tych samych rozdań: {others}."
            )
        answer = QMessageBox.question(
            self,
            "Usuń statystyki bota",
            text + "\n\nNie da się tego cofnąć.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        try:
            deleted = delete_bot_records(
                label, self.log_path, self.exchange_path, self.illegal_path, self.api_error_path
            )
        except (OSError, UnicodeDecodeError) as exc:
            self.status.setText(f"⚠ Nie udało się usunąć rekordów: {exc}")
            return
        self._note = (
            f"usunięto „{label}”: ruchy {deleted.trajectories}"
            + (f" (+{deleted.other_trajectories} z tych samych rozdań)" if deleted.other_trajectories else "")
            + f", wymiany z API {deleted.exchanges}, nielegalne {deleted.illegal}, błędy API {deleted.api_errors}"
        )
        self.refresh()

    def _show_model(self, m: ModelQuality | None) -> None:
        if m is None:
            self.detail_title.setText("Brak ruchów do oceny")
            self.correctness_gauge.set_value(None)
            self.aggressiveness_gauge.set_value(None)
            self.detail_stats.setText("")
            self.verdicts.set_shares({})
            self.scenarios.set_rows([])
            return
        self.detail_title.setText(m.model)
        self.correctness_gauge.set_value(m.correctness)
        self.aggressiveness_gauge.set_value(m.aggressiveness)
        self.detail_stats.setText(
            f"Ruchy: {m.moves} (wybory {m.decisions}, wymuszone {m.forced}"
            + (f", nielegalne {m.illegal}" if m.illegal else "")
            + ")"
        )
        self.verdicts.set_shares(
            {v: (m.verdicts[v] / m.decisions if m.decisions else 0.0) for v in VERDICTS}
        )
        self.scenarios.set_rows(
            [
                BarRow(
                    SCENARIO_NAMES.get(name, name),
                    sum(values) / len(values),
                    correctness_color(sum(values) / len(values)),
                    f"×{len(values)}",
                )
                for name, values in sorted(m.scenarios.items())
            ]
        )

    def _copy(self) -> None:
        if self.result is not None and self.result.report is not None:
            QGuiApplication.clipboard().setText(self.result.text)
            self.status.setText(f"{self._summary} · skopiowano do schowka")
