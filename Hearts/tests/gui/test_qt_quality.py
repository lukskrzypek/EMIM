"""Quality panel, charts and bot insight tab (offscreen)."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QImage

from controllers.base import PlayerController
from controllers.smart_bot import SmartHeartsBot
from engine.game import HeartsGameEngine, PlayerObservation
from gui.core.events import MovePlayed, SessionFinished, SessionStarted
from gui.core.human_controller import HumanGuiController
from gui.core.live_evaluator import LiveEvaluator
from gui.core.seat_config import SeatConfig, SeatKind, SessionConfig
from gui.qt.game_view import GameView
from gui.qt.quality.insight_panel import BotInsightPanel
from gui.qt.quality.quality_panel import QualityPanel
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
from gui.qt.session_controller import SessionController


class Talker(PlayerController):
    model_name = "talker"

    def select_move(self, observation: PlayerObservation) -> str:
        self.last_reasoning = f"gram {observation.legal_moves[-1]} bo tak"
        return observation.legal_moves[-1]


def _factory(seed: int):  # type: ignore[no-untyped-def]
    return lambda n, k: HeartsGameEngine(n, seed=seed + k)


def _distinct(widget) -> int:  # type: ignore[no-untyped-def]
    widget.resize(widget.sizeHint().expandedTo(widget.minimumSize()).expandedTo(widget.size()))
    image: QImage = widget.grab().toImage()
    return len({image.pixel(x, y) for x in range(0, image.width(), 3) for y in range(0, image.height(), 3)})


def _bot_session(n: int = 3, seed: int = 4, evaluator: LiveEvaluator | None = None):  # type: ignore[no-untyped-def]
    config = SessionConfig(
        tuple(SeatConfig(SeatKind.SMART, smart_samples=0) for _ in range(n)), log_path=None
    )
    controllers: dict[str, PlayerController] = {
        f"P{i}": (Talker() if i == 0 else SmartHeartsBot(num_samples=0, seed=i)) for i in range(n)
    }
    session = SessionController(
        config,
        controllers=controllers,
        engine_factory=_factory(seed),
        analyzer=evaluator if evaluator is not None else LiveEvaluator(),
    )
    session.pace.delay = 0.0
    return session


# ------------------------------------------------------------------ charts


def test_chart_widgets_paint_something(qtbot) -> None:  # type: ignore[no-untyped-def]
    gauge = GaugeWidget("Poprawność")
    gauge.set_value(83.0, "ok")
    verdicts = VerdictBar()
    verdicts.set_shares({"optymalne": 0.5, "poprawne": 0.25, "wątpliwe": 0.15, "niepoprawne": 0.1})
    spark = Sparkline()
    spark.set_points([SparkPoint(v, correctness_color(v)) for v in (95, 60, 30, 80, 100)])
    bars = BarList(label_width=40)
    bars.set_rows([BarRow("10♥", 90, "#3ecf8e", "zagrana", True), BarRow("2♣", 20, "#ef5b5b", "")])
    for widget in (gauge, verdicts, spark, bars):
        qtbot.addWidget(widget)
        assert _distinct(widget) > 3, type(widget).__name__


def test_empty_charts_do_not_crash(qtbot) -> None:  # type: ignore[no-untyped-def]
    for widget in (GaugeWidget("x"), VerdictBar(), Sparkline(), BarList(empty_text="nic")):
        qtbot.addWidget(widget)
        widget.grab()


def test_correctness_colours_follow_the_verdict_thresholds() -> None:
    assert correctness_color(95) == VERDICT_COLORS["optymalne"]
    assert correctness_color(70) == VERDICT_COLORS["poprawne"]
    assert correctness_color(40) == VERDICT_COLORS["wątpliwe"]
    assert correctness_color(10) == VERDICT_COLORS["niepoprawne"]


def test_bar_list_grows_with_its_rows(qtbot) -> None:  # type: ignore[no-untyped-def]
    bars = BarList()
    qtbot.addWidget(bars)
    bars.set_rows([BarRow("a", 1, "#fff")])
    one = bars.height()
    bars.set_rows([BarRow("a", 1, "#fff")] * 4)
    assert bars.height() > one


# ------------------------------------------------------------------- panel


def test_quality_panel_tracks_a_bot_game(qtbot) -> None:  # type: ignore[no-untyped-def]
    session = _bot_session(3)
    view = GameView(session)
    qtbot.addWidget(view)
    view.resize(1300, 850)
    view.show()
    finished: list[SessionFinished] = []
    moves: list[MovePlayed] = []
    session.eventsReady.connect(lambda b: moves.extend(e for e in b if isinstance(e, MovePlayed)))
    session.eventsReady.connect(lambda b: finished.extend(e for e in b if isinstance(e, SessionFinished)))
    session.start()
    qtbot.waitUntil(lambda: bool(finished), timeout=15000)

    panel = view.quality_panel
    assert panel.quality.total_moves == len(moves) == 3 * 17
    assert panel.table.rowCount() == 3
    texts = [panel.table.item(r, 0).text() for r in range(3)]
    assert texts[0].startswith("P0 ·")
    assert panel.table.item(0, 1).text() != "–"  # correctness filled in
    assert panel.follow.isChecked()
    assert panel.title.text().startswith(panel.quality.last.player_id)  # type: ignore[union-attr]
    assert "zagrał" in panel.last_title.text()
    assert len(panel.last_ranking.rows) == len(panel.quality.last.ranking)  # type: ignore[union-attr]
    assert sum(1 for r in panel.last_ranking.rows if r.emphasis) == 1
    assert not panel.hint_card.isVisible()
    session.close()


def test_clicking_a_row_pins_that_seat(qtbot) -> None:  # type: ignore[no-untyped-def]
    session = _bot_session(3)
    view = GameView(session)
    qtbot.addWidget(view)
    view.show()
    done: list[SessionFinished] = []
    session.eventsReady.connect(lambda b: done.extend(e for e in b if isinstance(e, SessionFinished)))
    session.start()
    qtbot.waitUntil(lambda: bool(done), timeout=15000)

    panel = view.quality_panel
    chosen: list[str] = []
    panel.seatSelected.connect(chosen.append)
    panel._on_row_clicked(2, 0)
    assert chosen == ["P2"]
    assert not panel.follow.isChecked()
    assert panel.title.text().startswith("P2")
    assert "P2" in panel.last_title.text()
    panel._on_row_clicked(0, 0)
    assert panel.title.text().startswith("P0")
    session.close()


def test_live_toggle_switches_the_evaluator_and_explains_it(qtbot) -> None:  # type: ignore[no-untyped-def]
    evaluator = LiveEvaluator()
    panel = QualityPanel({"P0": "A", "P1": "B"}, has_human=False, evaluator=evaluator)
    qtbot.addWidget(panel)
    assert panel.live_check.isChecked() and not panel.notice.isVisibleTo(panel)
    panel.live_check.setChecked(False)
    assert evaluator.enabled is False
    assert panel.notice.isVisibleTo(panel)
    panel.live_check.setChecked(True)
    assert evaluator.enabled is True and not panel.notice.isVisibleTo(panel)

    none = QualityPanel({"P0": "A"}, has_human=False, evaluator=None)
    qtbot.addWidget(none)
    assert not none.live_check.isEnabled() and none.notice.isVisibleTo(none)
    assert not none.hint_check.isVisibleTo(none)  # no human, no hints


def test_session_without_an_evaluator_still_runs(qtbot) -> None:  # type: ignore[no-untyped-def]
    config = SessionConfig((SeatConfig(SeatKind.SMART, smart_samples=0),) * 3, log_path=None)
    session = SessionController(
        config,
        controllers={f"P{i}": SmartHeartsBot(num_samples=0, seed=i) for i in range(3)},
        engine_factory=_factory(1),
    )
    session.pace.delay = 0.0
    view = GameView(session)
    qtbot.addWidget(view)
    done: list[SessionFinished] = []
    session.eventsReady.connect(lambda b: done.extend(e for e in b if isinstance(e, SessionFinished)))
    session.start()
    qtbot.waitUntil(lambda: bool(done), timeout=15000)
    assert view.quality_panel.quality.total_moves == 0
    assert not view.quality_panel.live_check.isEnabled()
    session.close()


# -------------------------------------------------------------------- hints


def test_hints_for_a_human_match_the_analysis_of_the_move(qtbot) -> None:  # type: ignore[no-untyped-def]
    config = SessionConfig(
        (SeatConfig(SeatKind.HUMAN), SeatConfig(SeatKind.SMART, smart_samples=0)), log_path=None
    )
    human = HumanGuiController()
    session = SessionController(
        config,
        controllers={"P0": human, "P1": SmartHeartsBot(num_samples=0, seed=1)},
        engine_factory=_factory(3),
        analyzer=LiveEvaluator(),
    )
    session.pace.delay = 0.0
    view = GameView(session)
    qtbot.addWidget(view)
    view.resize(1300, 850)
    view.show()
    qtbot.waitExposed(view)
    panel = view.quality_panel
    assert panel.hint_check.isVisibleTo(panel) and not panel.hint_check.isChecked()
    moves: list[MovePlayed] = []
    session.eventsReady.connect(lambda b: moves.extend(e for e in b if isinstance(e, MovePlayed)))
    session.start()

    qtbot.waitUntil(lambda: view.model.interactive_player == "P0", timeout=5000)
    assert not panel.hint_card.isVisible()  # off by default: no peeking by accident
    panel.hint_check.setChecked(True)
    assert panel.hint is not None and panel.hint_card.isVisibleTo(panel)
    shown = panel.hint
    assert {m.card for m in shown.ranking} == set(view.model.legal_moves)
    assert len(panel.hint_ranking.rows) == len(shown.ranking)

    played = sorted(view.model.legal_moves)[0]
    assert human.submit(played)
    qtbot.waitUntil(lambda: any(m.player_id == "P0" for m in moves), timeout=5000)
    mine = next(m for m in moves if m.player_id == "P0")
    assert mine.analysis.ranking == shown.ranking  # what we hinted is what was judged
    assert mine.analysis.chosen == played
    session.close()


def test_hint_is_never_computed_behind_the_hot_seat_veil(qtbot) -> None:  # type: ignore[no-untyped-def]
    config = SessionConfig((SeatConfig(SeatKind.HUMAN), SeatConfig(SeatKind.HUMAN)), log_path=None)
    session = SessionController(
        config,
        controllers={"P0": HumanGuiController(), "P1": HumanGuiController()},
        engine_factory=_factory(3),
        analyzer=LiveEvaluator(),
    )
    session.pace.delay = 0.0
    view = GameView(session)
    qtbot.addWidget(view)
    view.resize(1300, 850)
    view.show()
    qtbot.waitExposed(view)
    view.quality_panel.hint_check.setChecked(True)
    session.start()
    qtbot.waitUntil(view.table.veil.isVisible, timeout=5000)
    assert view.quality_panel.hint is None and not view.quality_panel.hint_card.isVisible()
    qtbot.mouseClick(view.table.veil.button, Qt.MouseButton.LeftButton)
    assert view.quality_panel.hint is not None and view.quality_panel.hint_card.isVisibleTo(view.quality_panel)
    session.close()


# ------------------------------------------------------------------ insight


def test_insight_tab_shows_reasoning_and_think_times(qtbot) -> None:  # type: ignore[no-untyped-def]
    session = _bot_session(3)
    view = GameView(session)
    qtbot.addWidget(view)
    view.resize(1300, 850)
    view.show()
    done: list[SessionFinished] = []
    session.eventsReady.connect(lambda b: done.extend(e for e in b if isinstance(e, SessionFinished)))
    session.start()
    qtbot.waitUntil(lambda: bool(done), timeout=15000)

    insight = view.insight
    assert insight.seat_box.count() == 3
    assert not insight.memory.isVisibleTo(insight)  # no AI seat
    # follow mode shows whoever moved last; pin the 'Talker' seat to read its text
    insight.follow.setChecked(False)
    insight.seat_box.setCurrentIndex(insight.seat_box.findData("P0"))
    insight._on_seat_chosen(0)
    seat = insight.model.seats["P0"]
    assert seat.moves == 17
    assert insight.entries.count() == 17
    assert insight.reasoning.toPlainText().startswith("gram ")
    assert "talker" in insight.status.text() and "17 ruchów" in insight.status.text()
    assert any(v in insight.entries.item(0).text() for v in VERDICT_COLORS)  # the verdict is listed too
    session.close()


def test_insight_tab_reads_the_ai_memory_only_for_ai_seats(qtbot) -> None:  # type: ignore[no-untyped-def]
    asked: list[str] = []

    def reader(model: str) -> str:
        asked.append(model)
        return f"notatki {model}"

    panel = BotInsightPanel(
        {"P0": "Człowiek", "P1": "Smart", "P2": "openai/gpt-oss-20b"},
        ("P0",),
        memory_models={"P2": "openai/gpt-oss-20b"},
        memory_reader=reader,
    )
    qtbot.addWidget(panel)
    panel.show()
    assert list(panel.model.seats) == ["P1", "P2"]  # the human has no reasoning to show
    panel.follow.setChecked(False)
    panel.seat_box.setCurrentIndex(0)
    panel._on_seat_chosen(0)
    assert not panel.memory.isVisible()
    panel.seat_box.setCurrentIndex(1)
    panel._on_seat_chosen(1)
    assert panel.memory.isVisible()
    assert panel.memory.toPlainText() == "notatki openai/gpt-oss-20b"
    assert asked and set(asked) == {"openai/gpt-oss-20b"}
    panel.apply([SessionStarted(("P0", "P1", "P2"), {"P0": "H", "P1": "S", "P2": "G"}, 1)])
    assert panel.seat_box.count() == 2


def test_insight_tab_is_empty_without_bots(qtbot) -> None:  # type: ignore[no-untyped-def]
    panel = BotInsightPanel({"P0": "Człowiek"}, ("P0",))
    qtbot.addWidget(panel)
    panel.show()
    assert panel.empty.isVisible() and not panel.entries.isVisible()


# ------------------------------------------------------------ average response time


def test_quality_panel_shows_the_average_response_time(qtbot) -> None:  # type: ignore[no-untyped-def]
    session = _bot_session(3)
    view = GameView(session)
    qtbot.addWidget(view)
    view.resize(1300, 850)
    view.show()
    moves: list[MovePlayed] = []
    finished: list[SessionFinished] = []
    session.eventsReady.connect(lambda b: moves.extend(e for e in b if isinstance(e, MovePlayed)))
    session.eventsReady.connect(lambda b: finished.extend(e for e in b if isinstance(e, SessionFinished)))
    session.start()
    qtbot.waitUntil(lambda: bool(finished), timeout=15000)

    panel = view.quality_panel
    column = panel.table.columnCount() - 1
    assert panel.table.horizontalHeaderItem(column).text() == "Śr. czas"
    for row, pid in enumerate(panel.quality.seats):
        times = [m.think_seconds for m in moves if m.player_id == pid]
        seat = panel.quality.seats[pid]
        assert seat.think_moves == len(times) == 17
        assert seat.avg_think == sum(times) / len(times)
        assert panel.table.item(row, column).text() == f"{seat.avg_think:.2f} s"
    assert "średni czas odpowiedzi" in panel.stats_line.text()
    session.close()


def test_response_time_is_counted_for_bots_only() -> None:
    from gui.core.live_quality import LiveQuality

    quality = LiveQuality({"P0": "A", "P1": "B"})
    assert quality.seats["P0"].avg_think is None
    quality.add_think("P0", 1.0)
    quality.add_think("P0", 3.0)
    seat = quality.seats["P0"]
    assert (seat.avg_think, seat.think_max, seat.think_moves) == (2.0, 3.0, 2)
    assert quality.seats["P1"].avg_think is None

    from gui.qt.quality.quality_panel import HUMAN_MODEL

    assert HumanGuiController.model_name == HUMAN_MODEL  # the panel skips humans by this name
