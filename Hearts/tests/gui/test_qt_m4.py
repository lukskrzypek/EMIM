"""Report view, settings, params dialog, shortcuts (offscreen)."""

from __future__ import annotations

import threading
from pathlib import Path

import pytest
from PySide6.QtCore import QSettings, Qt
from PySide6.QtWidgets import QPushButton

from controllers.smart_bot import SmartHeartsBot
from engine.state import GameState
from evaluation.params import Params
from evaluation.report import build_report
from evaluation.trajectories import load_moves
from gui.core.events import SessionFinished
from gui.core.human_controller import HumanGuiController
from gui.core.live_evaluator import LiveEvaluator
from gui.core.lobby_state import LobbyState, default_seats
from gui.core.report_service import ReportResult
from gui.core.seat_config import SeatConfig, SeatKind, SessionConfig
from gui.qt.game_view import GameView
from gui.qt.lobby.lobby_view import LobbyView
from gui.qt.main_window import MainWindow
from gui.qt.quality.params_dialog import ParamsDialog
from gui.qt.quality.quality_panel import QualityPanel
from gui.qt.report import report_view as report_module
from gui.qt.report.report_view import ReportView
from gui.qt.session_controller import SessionController
from gui.qt.settings import AppSettings, ViewPrefs
from gui.qt.table.pixmap_card_renderer import PixmapCardRenderer
from gui.qt.table.renderer_factory import default_renderer, has_png_deck
from gui.qt.table.vector_card_renderer import VectorCardRenderer
from test_core_live_quality import _play


def _settings(tmp_path: Path, name: str = "s.ini") -> AppSettings:
    return AppSettings(QSettings(str(tmp_path / name), QSettings.Format.IniFormat))


def _factory(seed: int):  # type: ignore[no-untyped-def]
    return lambda n: GameState.new(n, seed=seed, start_deal=n * 7)  # just the last deal


def _bot_session(n: int = 3):  # type: ignore[no-untyped-def]
    config = SessionConfig(tuple(SeatConfig(SeatKind.SMART, smart_samples=0) for _ in range(n)), log_path=None)
    session = SessionController(
        config,
        controllers={f"P{i}": SmartHeartsBot(num_samples=0, seed=i) for i in range(n)},
        engine_factory=_factory(4),
        analyzer=LiveEvaluator(),
    )
    session.pace.delay = 0.0
    return session


# ----------------------------------------------------------------- settings


def test_settings_round_trip_through_a_file(tmp_path: Path) -> None:
    first = _settings(tmp_path)
    seats = list(default_seats())
    seats[1] = SeatConfig(SeatKind.AI, ai_model="openai/gpt-oss-20b",
                          ai_guidelines="Avoid hearts.")
    state = LobbyState(players=3, seats=tuple(seats))
    prefs = ViewPrefs(four_color=True, reveal_bots=True, hints=True, live_eval=False, after_trick=True, delay=0.4)
    first.save_lobby_state(state)
    first.save_view_prefs(prefs)
    first.save_report_ignored("human")
    first.store.sync()

    second = _settings(tmp_path)  # a "restart"
    assert second.lobby_state() == state
    assert second.view_prefs() == prefs
    assert second.report_ignored() == "human"


def test_empty_or_damaged_settings_fall_back_to_defaults(tmp_path: Path) -> None:
    fresh = _settings(tmp_path, "fresh.ini")
    assert fresh.lobby_state() == LobbyState()
    assert fresh.view_prefs() == ViewPrefs()
    assert fresh.geometry() is None
    assert fresh.report_ignored() == "human, smart_bot"

    damaged = _settings(tmp_path, "damaged.ini")
    damaged.store.setValue("lobby/state", "{{{")
    damaged.store.setValue("view/delay", "fast")
    damaged.store.setValue("window/geometry", "not bytes")
    assert damaged.lobby_state() == LobbyState()
    assert damaged.view_prefs().delay is None
    assert damaged.geometry() is None


def test_lobby_restores_every_choice_including_hidden_seats(qtbot) -> None:  # type: ignore[no-untyped-def]
    lobby = LobbyView()
    qtbot.addWidget(lobby)
    seats = list(default_seats())
    seats[0] = SeatConfig(SeatKind.SMART, smart_samples=5)
    seats[3] = SeatConfig(SeatKind.SMART, smart_samples=9)  # hidden at 3 players
    state = LobbyState(players=3, seats=tuple(seats))
    lobby.apply_state(state)
    assert lobby.num_players == 3
    assert lobby.rows[0].seat_kind is SeatKind.SMART and lobby.rows[0].samples.value() == 5
    assert lobby.state() == state
    assert lobby.build_config().num_players == 3


def test_main_window_remembers_the_lobby_and_the_geometry(qtbot, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    settings = _settings(tmp_path)
    window = MainWindow(settings, log_path=tmp_path / "none.jsonl")
    qtbot.addWidget(window)
    window.lobby.players.setCurrentIndex(0)  # 3 players
    window.lobby.rows[1].kind.setCurrentIndex(0)  # a human on seat 1
    window.start_session(window.lobby.build_config())
    assert settings.lobby_state().players == 3
    window.close()
    assert settings.geometry() is not None

    again = MainWindow(_settings(tmp_path), log_path=tmp_path / "none.jsonl")
    qtbot.addWidget(again)
    assert again.lobby.num_players == 3


def test_rematch_restarts_with_the_same_seats(qtbot, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    window = MainWindow(_settings(tmp_path), log_path=tmp_path / "none.jsonl")
    qtbot.addWidget(window)
    config = SessionConfig((SeatConfig(SeatKind.SMART, smart_samples=0),) * 3, log_path=None)
    window.rematch()  # nothing played yet: nothing to repeat
    assert window.game is None
    window.start_session(config)
    first = window.session
    window.game.rematchRequested.emit()
    assert window.session is not first and window.session.config == config
    assert window.stack.currentWidget() is window.game
    window.close()  # closing right after a start must not crash (deleted before any event loop)


# ------------------------------------------------------------------- report


def _report_view(qtbot, log: Path, **kw) -> ReportView:  # type: ignore[no-untyped-def]
    view = ReportView(log, **kw)
    qtbot.addWidget(view)
    view.resize(1100, 700)
    view.show()
    return view


def test_report_view_shows_the_offline_report(qtbot, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    log = tmp_path / "trajectories.jsonl"
    _play(4, seed=31, log=log, start_deal=27)  # the last two deals
    view = _report_view(qtbot, log)
    with qtbot.waitSignal(view.finished, timeout=10000):
        view.refresh()

    expected = build_report(load_moves(log)).models
    assert view.table.rowCount() == 2
    names = [view.table.item(r, 0).text() for r in range(2)]
    assert set(names) == set(expected)
    best = max(expected.values(), key=lambda m: m.correctness)
    assert names[0] == best.model  # the best model comes first
    assert view.detail_title.text() == best.model  # first row is selected
    assert view.table.item(0, 3).text() == f"{best.correctness:.1f}"
    assert view.correctness_gauge.value == pytest.approx(best.correctness)
    assert "Rekordów w logu: 104" in view.status.text()
    assert "Ocena jakości ruchów botów" in view.text.toPlainText()
    assert view.refresh_button.isEnabled() and view.copy_button.isEnabled()

    view.table.selectRow(1)
    assert view.detail_title.text() == names[1]
    assert view.scenarios.rows  # per-scenario bars for the other model


def test_report_view_ignores_models_and_remembers_the_choice(qtbot, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    log = tmp_path / "trajectories.jsonl"
    _play(3, seed=2, log=log)
    settings = _settings(tmp_path)
    view = _report_view(qtbot, log, settings=settings)
    view.ignored.setText("smart_bot")
    with qtbot.waitSignal(view.finished, timeout=10000):
        view.refresh()
    assert view.table.rowCount() == 1 and view.table.item(0, 0).text() == "last_legal"
    assert "pominięto" in view.status.text()
    assert settings.report_ignored() == "smart_bot"


def test_report_view_explains_a_missing_log(qtbot, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    view = _report_view(qtbot, tmp_path / "missing.jsonl")
    with qtbot.waitSignal(view.finished, timeout=10000):
        view.refresh()
    assert "Brak pliku" in view.status.text()
    assert view.table.rowCount() == 0 and not view.copy_button.isEnabled()
    assert view.refresh_button.isEnabled()


def test_report_is_computed_off_the_ui_thread_and_stale_answers_are_dropped(qtbot, tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    threads: list[str] = []
    real = report_module.load_report

    def spy(path, ignored=()):  # type: ignore[no-untyped-def]
        threads.append(threading.current_thread().name)
        return real(path, ignored)

    monkeypatch.setattr(report_module, "load_report", spy)
    log = tmp_path / "trajectories.jsonl"
    _play(3, seed=1, log=log)
    view = _report_view(qtbot, log)
    with qtbot.waitSignal(view.finished, timeout=10000):
        view.refresh()
    assert threads and threads[0] != threading.main_thread().name

    stale = ReportResult(log, (), error="old")
    view._on_done(view._request - 1, stale)  # an answer to an earlier request
    assert view.result is not stale and "old" not in view.status.text()


def test_report_text_can_be_copied(qtbot, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    from PySide6.QtGui import QGuiApplication

    log = tmp_path / "trajectories.jsonl"
    _play(3, seed=1, log=log)
    view = _report_view(qtbot, log)
    with qtbot.waitSignal(view.finished, timeout=10000):
        view.refresh()
    view.copy_button.click()
    assert QGuiApplication.clipboard().text().startswith("Ocena jakości ruchów botów")
    assert "skopiowano" in view.status.text()


def test_lobby_opens_the_report_and_back(qtbot, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    log = tmp_path / "trajectories.jsonl"
    _play(3, seed=1, log=log)
    window = MainWindow(_settings(tmp_path), log_path=log)
    qtbot.addWidget(window)
    window.show()
    with qtbot.waitSignal(window.report.finished, timeout=10000):
        window.lobby.report_button.click()
    assert window.stack.currentWidget() is window.report
    assert window.report.table.rowCount() >= 1
    window.report.back_button.click()
    assert window.stack.currentWidget() is window.lobby


# ------------------------------------------------------------------- params


def test_params_dialog_edits_and_restores(qtbot) -> None:  # type: ignore[no-untyped-def]
    dialog = ParamsDialog(Params())
    qtbot.addWidget(dialog)
    assert len(dialog.editors) == 26
    assert dialog.params() == Params()
    dialog.editors["overtake_rate"].setValue(0.25)
    dialog.editors["heavy_min_cards"].setValue(5)
    changed = dialog.params()
    assert changed.overtake_rate == 0.25 and changed.heavy_min_cards == 5
    assert isinstance(changed.heavy_min_cards, int)
    dialog.restore_defaults()
    assert dialog.params() == Params()
    assert all(box.toolTip() for box in dialog.editors.values())


def test_panel_applies_custom_params_and_warns(qtbot) -> None:  # type: ignore[no-untyped-def]
    evaluator = LiveEvaluator()
    panel = QualityPanel({"P0": "A"}, has_human=False, evaluator=evaluator)
    qtbot.addWidget(panel)
    panel.show()
    changed: list[bool] = []
    panel.paramsChanged.connect(lambda: changed.append(True))

    custom = Params(overtake_rate=0.1)
    panel.apply_params(custom)
    assert evaluator.params == custom and changed
    assert panel.notice.isVisible() and "Własne parametry" in panel.notice.text()

    panel.apply_params(Params())  # back to the defaults: no warning, evaluator uses its own defaults
    assert evaluator.params is None
    assert not panel.notice.isVisible()
    assert panel.params_button.isEnabled()

    none = QualityPanel({"P0": "A"}, has_human=False, evaluator=None)
    qtbot.addWidget(none)
    assert not none.params_button.isEnabled()
    none.apply_params(custom)  # harmless


# -------------------------------------------------------------- game view


def test_game_view_applies_and_saves_preferences(qtbot, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    settings = _settings(tmp_path)
    settings.save_view_prefs(ViewPrefs(four_color=True, after_trick=True, delay=0.5))
    session = _bot_session(3)
    view = GameView(session, settings=settings)
    qtbot.addWidget(view)
    assert session.pace.delay == 0.5
    assert view.four_color.isChecked() and view.controls.after_trick.isChecked()
    assert view.renderer.four_color

    view.four_color.setChecked(False)
    view.controls.speed.setValue(view.controls.speed.maximum())  # MAX
    saved = settings.view_prefs()
    assert saved.four_color is False and saved.delay == 0.0 and saved.after_trick is True
    session.close()


def test_hints_and_live_evaluation_choices_are_restored(qtbot, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    settings = _settings(tmp_path)
    settings.save_view_prefs(ViewPrefs(hints=True, reveal_bots=True, live_eval=False))
    config = SessionConfig(
        (SeatConfig(SeatKind.HUMAN), *(SeatConfig(SeatKind.SMART, smart_samples=0),) * 2), log_path=None
    )
    evaluator = LiveEvaluator()
    session = SessionController(
        config,
        controllers={
            "P0": HumanGuiController(),
            "P1": SmartHeartsBot(num_samples=0, seed=1),
            "P2": SmartHeartsBot(num_samples=0, seed=2),
        },
        engine_factory=_factory(3),
        analyzer=evaluator,
    )
    view = GameView(session, settings=settings)
    qtbot.addWidget(view)
    assert view.quality_panel.hint_check.isChecked()
    assert view.reveal.isChecked() and view.model.reveal_bots
    assert not view.quality_panel.live_check.isChecked() and evaluator.enabled is False
    session.close()


def test_bot_only_game_does_not_save_the_locked_reveal_checkbox(qtbot, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    settings = _settings(tmp_path)
    session = _bot_session(3)
    view = GameView(session, settings=settings)
    qtbot.addWidget(view)
    view.four_color.setChecked(True)  # any change triggers a save
    assert settings.view_prefs().reveal_bots is False  # "all visible" is forced, not a preference
    session.close()


def test_png_deck_is_used_when_the_folder_exists(qtbot, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    empty = tmp_path / "none"
    assert not has_png_deck(empty)
    assert isinstance(default_renderer(empty), VectorCardRenderer)
    deck = tmp_path / "cards"
    deck.mkdir()
    assert isinstance(default_renderer(deck), VectorCardRenderer)  # a folder without images is no deck

    VectorCardRenderer().pixmap("QS", 140).save(str(deck / "QS.png"))
    renderer = default_renderer(deck)
    assert isinstance(renderer, PixmapCardRenderer)
    assert not renderer.pixmap("QS", 70).isNull()
    assert not renderer.pixmap("2C", 70).isNull()  # no 2C.png: drawn by the vector fallback


def test_stored_four_colour_choice_survives_a_png_deck(qtbot, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    settings = _settings(tmp_path)
    settings.save_view_prefs(ViewPrefs(four_color=True))
    session = _bot_session(3)
    deck = tmp_path / "cards"
    deck.mkdir()
    VectorCardRenderer().pixmap("QS", 140).save(str(deck / "QS.png"))
    view = GameView(session, settings=settings, renderer=default_renderer(deck))
    qtbot.addWidget(view)
    assert not view.four_color.isEnabled()
    view.controls.after_trick.setChecked(True)  # any change saves the preferences
    assert settings.view_prefs().four_color is True
    session.close()


# ---------------------------------------------------------------- shortcuts


def _fire(view: GameView, key: str) -> None:
    shortcut = next(s for s in view.shortcuts if s.key().toString() == key)
    shortcut.activated.emit()


def test_shortcuts_pause_step_and_change_the_tempo(qtbot) -> None:  # type: ignore[no-untyped-def]
    session = _bot_session(3)
    session.pace.delay = 1.0
    view = GameView(session)
    qtbot.addWidget(view)
    keys = {s.key().toString() for s in view.shortcuts}
    assert {"Space", "N", "+", "-", "Ctrl+1", "Ctrl+2", "Ctrl+3", "Ctrl+4"} <= keys
    assert all(s.context() == Qt.ShortcutContext.WidgetWithChildrenShortcut for s in view.shortcuts)

    assert not session.pace.paused
    _fire(view, "Space")
    assert session.pace.paused
    _fire(view, "Space")
    assert not session.pace.paused

    session.pace.pause()
    steps: list[bool] = []
    original = session.pace.step
    session.pace.step = lambda: (steps.append(True), original())[1]  # type: ignore[method-assign]
    _fire(view, "N")
    assert steps == [True]
    session.pace.resume()
    _fire(view, "N")  # not paused: nothing to step
    assert steps == [True]

    before = view.controls.speed.value()
    _fire(view, "+")
    assert view.controls.speed.value() == before + 1 and session.pace.delay < 1.0
    _fire(view, "-")
    _fire(view, "-")
    assert view.controls.speed.value() == before - 1

    _fire(view, "Ctrl+3")
    assert view.tabs.currentIndex() == 2
    session.close()


def test_shortcuts_do_nothing_after_the_game_ended(qtbot) -> None:  # type: ignore[no-untyped-def]
    session = _bot_session(3)
    view = GameView(session)
    qtbot.addWidget(view)
    done: list[SessionFinished] = []
    session.eventsReady.connect(lambda b: done.extend(e for e in b if isinstance(e, SessionFinished)))
    session.start()
    qtbot.waitUntil(lambda: bool(done), timeout=15000)
    _fire(view, "Space")
    assert not session.pace.paused
    session.close()


def test_f11_toggles_fullscreen(qtbot, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    window = MainWindow(_settings(tmp_path), log_path=tmp_path / "x.jsonl")
    qtbot.addWidget(window)
    window.show()
    assert not window.isFullScreen()
    window._fullscreen_shortcut.activated.emit()
    assert window.isFullScreen()
    window._fullscreen_shortcut.activated.emit()
    assert not window.isFullScreen()


def test_pace_buttons_still_exist_for_the_mouse(qtbot) -> None:  # type: ignore[no-untyped-def]
    session = _bot_session(3)
    view = GameView(session)
    qtbot.addWidget(view)
    assert "Spacja" in view.controls.pause_button.toolTip()
    assert isinstance(view.controls.pause_button, QPushButton)
    session.close()