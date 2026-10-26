"""Live quality panel: per-seat leaderboard, gauges, verdicts, trend and the last move's alternatives."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from evaluation.params import Params
from gui.core.cardtext import pretty_card
from gui.core.bot_insight import read_ai_memory
from gui.core.events import GameEvent, MovePlayed, SessionFinished, SessionStarted
from gui.core.live_evaluator import LiveAnalysis, LiveEvaluator
from gui.core.live_quality import LiveQuality, SeatQuality
from gui.core.params_schema import is_default
from gui.qt.quality.memory_board import MemoryBoard
from gui.qt.quality.params_dialog import ParamsDialog
from gui.qt.quality.widgets import (
    VERDICT_COLORS,
    BarList,
    BarRow,
    GaugeWidget,
    Sparkline,
    SparkPoint,
    VerdictBar,
    correctness_color,
)
from gui.qt.theme import ACCENT, TEXT, TEXT_MUTED

SCENARIO_NAMES = {
    "only_move": "ruch wymuszony",
    "forced_take": "wymuszone wzięcie",
    "lead": "wyjście do lewy",
    "follow_take": "dokładam i biorę",
    "follow_duck": "dokładam i unikam",
    "void_discard": "zrzut (brak koloru)",
}
COLUMNS = ("Gracz", "Poprawn.", "Agres.", "Regret", "Wybory", "Śr. czas")
ROW_H = 26
HUMAN_MODEL = "human"  # model_name of a human seat: no response time to average


def _fmt(value: float | None, digits: int = 1) -> str:
    return "–" if value is None else f"{value:.{digits}f}"


def _card(title: str) -> tuple[QFrame, QVBoxLayout]:
    frame = QFrame()
    frame.setObjectName("card")
    layout = QVBoxLayout(frame)
    layout.setContentsMargins(12, 10, 12, 12)
    layout.setSpacing(6)
    heading = QLabel(title)
    heading.setObjectName("muted")
    layout.addWidget(heading)
    return frame, layout


def ranking_rows(analysis: LiveAnalysis) -> list[BarRow]:
    """Bars for all legal alternatives; the played card (if any) is emphasised."""
    rows = []
    for index, move in enumerate(analysis.ranking):
        played = move.card == analysis.chosen
        note = "zagrana" if played else "najlepsza" if index == 0 else ""
        rows.append(
            BarRow(
                label=pretty_card(move.card),
                value=move.correctness,
                colour=correctness_color(move.correctness),
                note=note,
                emphasis=played,
            )
        )
    return rows


class QualityPanel(QWidget):
    hintsToggled = Signal(bool)
    liveToggled = Signal(bool)
    seatSelected = Signal(str)
    paramsChanged = Signal()

    def __init__(
        self,
        labels: dict[str, str],
        *,
        has_human: bool,
        evaluator: LiveEvaluator | None,
        memory_models: Mapping[str, str] | None = None,
        memory_reader: Callable[[str], str] = read_ai_memory,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.evaluator = evaluator
        self.memory_board = MemoryBoard(memory_models or {}, labels, reader=memory_reader)
        self.quality = LiveQuality(labels)
        self.selected: str | None = None
        self.hint: LiveAnalysis | None = None

        # ---- switches
        self.live_check = QCheckBox("Ocena ruchów na żywo")
        self.live_check.setChecked(evaluator is not None and evaluator.enabled)
        self.live_check.setEnabled(evaluator is not None)
        self.hint_check = QCheckBox("Podpowiedzi dla człowieka")
        self.hint_check.setToolTip("Przed Twoim ruchem pokazuje ocenę wszystkich legalnych kart")
        self.hint_check.setVisible(has_human)
        self.follow = QCheckBox("Śledź ostatni ruch")
        self.follow.setChecked(True)
        self.params_button = QPushButton("Parametry oceny…")
        self.params_button.setEnabled(evaluator is not None)
        self.params_button.setToolTip("Strojone liczby ewaluatora (tylko oceny na żywo w tej sesji)")
        self.params_button.clicked.connect(self.open_params_dialog)
        self.notice = QLabel("")
        self.notice.setObjectName("warning")
        self.notice.setWordWrap(True)

        # ---- leaderboard
        self.table = QTableWidget(0, len(COLUMNS))
        self.table.setHorizontalHeaderLabels(COLUMNS)
        self.table.verticalHeader().hide()
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
        self.table.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.table.cellClicked.connect(self._on_row_clicked)

        # ---- detail of one seat
        self.title = QLabel("")
        self.title.setStyleSheet("font-size: 15px; font-weight: 600;")
        self.title.setWordWrap(True)
        self.stats_line = QLabel("")
        self.stats_line.setObjectName("muted")
        self.stats_line.setWordWrap(True)
        self.correctness_gauge = GaugeWidget("Poprawność")
        self.aggressiveness_gauge = GaugeWidget("Agresywność", graded=False)
        self.verdicts = VerdictBar()
        self.spark = Sparkline()
        self.scenarios = BarList(label_width=124, empty_text="brak ocenionych ruchów")

        # ---- last move + hint
        self.last_title = QLabel("")
        self.last_title.setWordWrap(True)
        self.last_title.setTextFormat(Qt.TextFormat.RichText)
        self.last_ranking = BarList(label_width=40, empty_text="Brak ruchu do pokazania")
        self.last_reasons = QLabel("")
        self.last_reasons.setObjectName("muted")
        self.last_reasons.setWordWrap(True)
        self.hint_title = QLabel("")
        self.hint_title.setWordWrap(True)
        self.hint_ranking = BarList(label_width=40)

        # ---- layout
        switches = QVBoxLayout()
        switches.setSpacing(4)
        switches.addWidget(self.live_check)
        switches.addWidget(self.hint_check)
        switches.addWidget(self.follow)
        switches.addWidget(self.params_button, alignment=Qt.AlignmentFlag.AlignLeft)
        switches.addWidget(self.notice)

        board_card, board = _card("Ranking jakości (ruchy z wyborem)")
        board.addWidget(self.table)

        detail_card, detail = _card("Wybrany gracz")
        detail.addWidget(self.title)
        gauges = QHBoxLayout()
        gauges.addWidget(self.correctness_gauge)
        gauges.addWidget(self.aggressiveness_gauge)
        detail.addLayout(gauges)
        detail.addWidget(self.stats_line)
        detail.addWidget(self._muted("Werdykty"))
        detail.addWidget(self.verdicts)
        detail.addWidget(self._muted("Poprawność kolejnych decyzji"))
        detail.addWidget(self.spark)
        detail.addWidget(self._muted("Według scenariusza"))
        detail.addWidget(self.scenarios)

        last_card, last = _card("Ostatni ruch i alternatywy")
        last.addWidget(self.last_title)
        last.addWidget(self.last_ranking)
        last.addWidget(self.last_reasons)

        self.hint_card, hint = _card("Podpowiedź")
        hint.addWidget(self.hint_title)
        hint.addWidget(self.hint_ranking)
        self.hint_card.hide()

        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(10)
        root.addLayout(switches)
        root.addWidget(self.hint_card)
        root.addWidget(board_card)
        root.addWidget(detail_card)
        root.addWidget(self.memory_board)
        root.addWidget(last_card)
        root.addStretch(1)

        self.live_check.toggled.connect(self._on_live_toggled)
        self.hint_check.toggled.connect(self._on_hint_toggled)
        self.follow.toggled.connect(lambda _: self.refresh())
        self._rebuild_rows()
        self.refresh()

    @staticmethod
    def _muted(text: str) -> QLabel:
        label = QLabel(text)
        label.setObjectName("muted")
        return label

    # ----------------------------------------------------------------- state

    @property
    def hints_enabled(self) -> bool:
        return self.hint_check.isVisibleTo(self) and self.hint_check.isChecked()

    def reset(self, labels: dict[str, str]) -> None:
        self.quality = LiveQuality(labels)
        self.selected = None
        self.hint = None
        self._rebuild_rows()
        self.refresh()

    def apply(self, events: Sequence[GameEvent]) -> None:
        changed = False
        for event in events:
            if isinstance(event, SessionStarted):
                self.reset(event.seat_labels)
                self.memory_board.refresh()
                changed = False
            elif isinstance(event, SessionFinished):
                self.memory_board.refresh()
            elif isinstance(event, MovePlayed):
                if event.model_name != HUMAN_MODEL:
                    self.quality.add_think(event.player_id, event.think_seconds)
                    changed = True
                if event.player_id in self.memory_board.seat_models:
                    self.memory_board.refresh(event.player_id)  # the bot may have rewritten it
                if isinstance(event.analysis, LiveAnalysis):
                    self.quality.record(event.analysis, event.move_number)
                    changed = True
        if changed:
            self.refresh()

    def set_hint(self, analysis: LiveAnalysis | None) -> None:
        self.hint = analysis
        self._refresh_hint()

    # ------------------------------------------------------------------- slots

    def _on_live_toggled(self, checked: bool) -> None:
        if self.evaluator is not None:
            self.evaluator.enabled = checked
        self.liveToggled.emit(checked)
        self.refresh()

    def open_params_dialog(self) -> None:
        if self.evaluator is None:
            return
        dialog = ParamsDialog(self.evaluator.params, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.apply_params(dialog.params())

    def apply_params(self, params: Params) -> None:
        """Use ``params`` for the following moves (earlier verdicts are kept as they were)."""
        if self.evaluator is None:
            return
        self.evaluator.params = None if is_default(params) else params
        self.refresh()
        self.paramsChanged.emit()  # the hint on screen must be re-rated

    def _on_hint_toggled(self, checked: bool) -> None:
        self.hintsToggled.emit(checked)
        if not checked:
            self.hint = None
        self._refresh_hint()

    def _on_row_clicked(self, row: int, _column: int) -> None:
        pid = list(self.quality.seats)[row]
        self.selected = pid
        self.follow.setChecked(False)  # triggers refresh
        self.seatSelected.emit(pid)
        self.refresh()

    # ------------------------------------------------------------------ views

    def _rebuild_rows(self) -> None:
        seats = self.quality.seats
        self.table.setRowCount(len(seats))
        for row in range(len(seats)):
            self.table.setRowHeight(row, ROW_H)
        self.table.setFixedHeight(28 + ROW_H * len(seats) + 4)

    def _shown_player(self) -> str | None:
        if self.follow.isChecked() and self.quality.last is not None:
            return self.quality.last.player_id
        if self.selected in self.quality.seats:
            return self.selected
        return next(iter(self.quality.seats), None)

    def refresh(self) -> None:
        shown = self._shown_player()
        self._refresh_notice()
        self._refresh_table(shown)
        if shown is not None:
            self._refresh_detail(self.quality.seats[shown])
            self._refresh_last(self.quality.last_by_player.get(shown), shown)
        self._refresh_hint()

    def _refresh_notice(self) -> None:
        if self.evaluator is None:
            self.notice.setText("Ocena na żywo niedostępna w tej sesji.")
        elif not self.evaluator.enabled:
            self.notice.setText("Ocena wyłączona: kolejne ruchy nie są oceniane (dotychczasowe wyniki zostają).")
        elif not is_default(self.evaluator.params):
            self.notice.setText(
                "Własne parametry oceny: kolejne ruchy są oceniane inaczej niż w raporcie z logu."
            )
        else:
            self.notice.setText("")
        self.notice.setVisible(bool(self.notice.text()))

    def _refresh_table(self, shown: str | None) -> None:
        for row, (pid, seat) in enumerate(self.quality.seats.items()):
            cells = (
                f"{pid} · {seat.label}",
                _fmt(seat.correctness),
                _fmt(seat.aggressiveness),
                _fmt(seat.avg_regret),
                str(seat.decisions),
                "–" if seat.avg_think is None else f"{seat.avg_think:.2f} s",
            )
            for col, text in enumerate(cells):
                existing = self.table.item(row, col)
                # ``setItem`` on an item the table already owns makes Qt print
                # "cannot insert an item that is already owned by another QTableWidget".
                item = existing if existing is not None else QTableWidgetItem()
                item.setText(text)
                if col:
                    item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                if col == 1 and seat.correctness is not None:
                    item.setForeground(QColor(correctness_color(seat.correctness)))
                elif pid == shown:
                    item.setForeground(QColor(ACCENT))
                else:
                    item.setForeground(QColor(TEXT))
                if existing is None:
                    self.table.setItem(row, col, item)

    def _refresh_detail(self, seat: SeatQuality) -> None:
        model = f" ({seat.model})" if seat.model and seat.model != seat.label else ""
        self.title.setText(f"{seat.player_id} · {seat.label}{model}")
        stats = seat.stats
        self.correctness_gauge.set_value(seat.correctness)
        self.aggressiveness_gauge.set_value(seat.aggressiveness)
        self.verdicts.set_shares(seat.verdict_shares())
        self.spark.set_points(
            [SparkPoint(r.correctness, correctness_color(r.correctness)) for r in seat.decision_records()]
        )
        rows = [
            BarRow(SCENARIO_NAMES.get(name, name), mean, correctness_color(mean), f"×{count}")
            for name, (count, mean) in seat.scenario_means().items()
        ]
        self.scenarios.set_rows(rows)
        best = _fmt(None if seat.best_rate is None else 100 * seat.best_rate, 0)
        self.stats_line.setText(
            f"Ruchy: {stats.moves} (wybory {seat.decisions}, wymuszone {stats.forced}"
            + (f", nielegalne {stats.illegal}" if stats.illegal else "")
            + f") · najlepsza karta w {best}% wyborów · średni regret {_fmt(seat.avg_regret)}"
            + (
                ""
                if seat.avg_think is None
                else f" · średni czas odpowiedzi {seat.avg_think:.2f} s (najdłuższy {seat.think_max:.2f} s)"
            )
        )

    def _refresh_last(self, analysis: LiveAnalysis | None, shown: str) -> None:
        if analysis is None or analysis.chosen_eval is None:
            self.last_title.setText(f"<span style='color:{TEXT_MUTED}'>{shown} jeszcze nie ruszał się w tej sesji.</span>")
            self.last_ranking.set_rows([])
            self.last_reasons.setText("")
            return
        chosen = analysis.chosen_eval
        colour = VERDICT_COLORS.get(chosen.verdict, TEXT_MUTED)
        regret = analysis.regret or 0.0
        self.last_title.setText(
            f"<b>{analysis.player_id}</b> zagrał <b>{pretty_card(chosen.card)}</b> — "
            f"<span style='color:{colour}'>{chosen.verdict} ({chosen.correctness:.0f})</span>"
            f" · regret {regret:.0f}"
            + (f" · agresywność: {chosen.aggressiveness_label}" if chosen.aggressiveness is not None else "")
        )
        self.last_ranking.set_rows(ranking_rows(analysis))
        reasons = chosen.reasons[:4]
        self.last_reasons.setText("\n".join(f"• {r}" for r in reasons))

    def _refresh_hint(self) -> None:
        show = self.hints_enabled and self.hint is not None
        self.hint_card.setVisible(show)
        if not show or self.hint is None:
            return
        best = self.hint.best
        self.hint_title.setText(
            f"<b>{self.hint.player_id}</b>: najlepsza karta to <b>{pretty_card(best.card)}</b> ({best.correctness:.0f})"
            if len(self.hint.ranking) > 1
            else f"<b>{self.hint.player_id}</b>: jedyna legalna karta {pretty_card(best.card)}"
        )
        self.hint_title.setTextFormat(Qt.TextFormat.RichText)
        self.hint_ranking.set_rows(ranking_rows(self.hint))
