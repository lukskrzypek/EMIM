"""Qt layer: bridge, lobby, control bar and the provisional game screen (offscreen)."""

from __future__ import annotations

import sys
import threading
import time
from pathlib import Path

import pytest
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QValidator

from controllers.base import PlayerController
from controllers.smart_bot import SmartHeartsBot
from engine.game import HeartsGameEngine, PlayerObservation
from gui.config import MAX_DELAY_S
from gui.core.events import MovePlayed, SessionFinished
from gui.core.game_runner import ErrorResolution
from gui.core.human_controller import HumanGuiController
from gui.core.pace import PaceControl
from gui.core.seat_config import SeatConfig, SeatKind, SessionConfig
from gui.qt.app import tune_gil
from gui.qt.bridge import QtBridge
from gui.qt.control_bar import ControlBar, delay_for, position_for
from gui.qt.game_view import GameView
from gui.qt.lobby import seat_row
from gui.qt.lobby.lobby_view import LobbyView
from gui.qt.main_window import MainWindow
from gui.qt.session_controller import SessionController
from gui.qt.table.card_item import CardItem


def _factory(seed: int):  # type: ignore[no-untyped-def]
    return lambda n, k: HeartsGameEngine(n, seed=seed + k)


def _smart_config(n: int = 3, deals: int = 1) -> SessionConfig:
    seats = tuple(SeatConfig(SeatKind.SMART, smart_samples=0) for _ in range(n))
    return SessionConfig(seats, deals=deals, log_path=None)


# -------------------------------------------------------------------- bridge


def test_bridge_delivers_events_from_another_thread_in_batches(qtbot) -> None:  # type: ignore[no-untyped-def]
    bridge = QtBridge(interval_ms=10)
    received: list[list[object]] = []
    bridge.eventsReady.connect(received.append)
    main_thread = threading.get_ident()
    delivered_in: list[int] = []
    bridge.eventsReady.connect(lambda _: delivered_in.append(threading.get_ident()))

    worker = threading.Thread(target=lambda: [bridge.push(i) for i in range(500)])  # type: ignore[arg-type]
    worker.start()
    qtbot.waitUntil(lambda: sum(len(b) for b in received) == 500, timeout=3000)
    assert [e for batch in received for e in batch] == list(range(500))
    assert set(delivered_in) == {main_thread}
    assert len(received) < 500  # coalesced, not one signal per event


def test_closed_bridge_drops_events(qtbot) -> None:  # type: ignore[no-untyped-def]
    bridge = QtBridge(interval_ms=10)
    received: list[object] = []
    bridge.eventsReady.connect(received.append)
    bridge.close()
    bridge.push("late")  # type: ignore[arg-type]
    qtbot.wait(60)
    assert not received


# --------------------------------------------------------------------- lobby


def test_lobby_defaults_and_config(qtbot) -> None:  # type: ignore[no-untyped-def]
    lobby = LobbyView()
    qtbot.addWidget(lobby)
    config = lobby.build_config()
    assert config.num_players == 4
    assert [s.kind for s in config.seats] == [SeatKind.HUMAN] + [SeatKind.SMART] * 3
    assert config.deals == 1 and config.seed is None
    assert config.log_path is not None  # logging stays on, as in the CLI

    lobby.players.setCurrentIndex(0)  # 2 players
    lobby.deals.setValue(5)
    lobby.rows[1].kind.setCurrentIndex(2)  # Groq
    config = lobby.build_config()
    assert config.num_players == 2 and config.deals == 5 and config.seed is None
    assert config.seats[1].kind is SeatKind.GROQ
    assert not hasattr(lobby, "seed") and not hasattr(lobby, "fixed_seed")  # no fixed deal in the GUI


def test_lobby_blocks_start_when_groq_is_unavailable(qtbot, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(
        seat_row, "availability_problem",
        lambda seat: "brak klucza" if seat.kind is SeatKind.GROQ else None,
    )
    lobby = LobbyView()
    qtbot.addWidget(lobby)
    assert lobby.start_button.isEnabled()  # nobody plays Groq yet
    lobby.rows[2].kind.setCurrentIndex(2)
    assert not lobby.start_button.isEnabled()
    assert "brak klucza" in lobby.message.text()
    lobby.rows[2].kind.setCurrentIndex(1)
    assert lobby.start_button.isEnabled()


def _models_file(tmp_path, *names: str):  # type: ignore[no-untyped-def]
    path = tmp_path / "groq_models.txt"
    path.write_text("\n".join(names) + "\n", encoding="utf-8")
    return path


def test_one_model_may_sit_twice_when_the_seats_have_different_names(qtbot, monkeypatch, tmp_path) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(seat_row, "availability_problem", lambda seat: None)  # pretend a key exists
    lobby = LobbyView(models_path=_models_file(tmp_path, "a/one", "b/two"))
    qtbot.addWidget(lobby)
    first, second, third = lobby.rows[1], lobby.rows[2], lobby.rows[3]
    first.kind.setCurrentIndex(2)  # Groq
    second.kind.setCurrentIndex(2)  # Groq: starts on a model the first seat does not play
    assert {first.model_name, second.model_name} == {"a/one", "b/two"}
    assert lobby.start_button.isEnabled() and not lobby.message.text()

    second.select_model(f" {first.model_name.upper()} ")  # same model on two seats, no names
    assert second.model_name == first.model_name
    assert "wspólną pamięć" in lobby.message.text() and "P1, P2" in lobby.message.text()
    assert not lobby.start_button.isEnabled()

    second.alias.setText("bold")  # one seat named: the files differ
    assert not lobby.message.text() and lobby.start_button.isEnabled()
    config = lobby.build_config()
    assert config.seats[1].groq_name == "" and config.seats[2].groq_name == "bold"
    assert config.seats[2].display_name == f"{first.model_name} (bold)"

    third.kind.setCurrentIndex(2)  # Groq again: takes the model nobody plays yet
    assert third.model_name == "b/two" and lobby.start_button.isEnabled()
    third.select_model(first.model_name)  # the model of the unnamed first seat: shared pad
    assert "wspólną pamięć" in lobby.message.text() and "P1, P3" in lobby.message.text()
    assert not lobby.start_button.isEnabled()
    third.alias.setText("BOLD")  # the file name ignores the case: clashes with the second seat
    assert "P2, P3" in lobby.message.text() and not lobby.start_button.isEnabled()
    third.alias.setText("calm")
    assert lobby.start_button.isEnabled() and not lobby.message.text()
    third.kind.setCurrentIndex(1)
    assert lobby.start_button.isEnabled()


def test_seat_name_is_short_and_safe_for_a_file_name(qtbot) -> None:  # type: ignore[no-untyped-def]
    lobby = LobbyView()
    qtbot.addWidget(lobby)
    row = lobby.rows[1]
    assert row.alias.maxLength() == 10
    lobby.show()
    row.kind.setCurrentIndex(2)  # Groq: the field is visible
    row.alias.setFocus()
    qtbot.keyClicks(row.alias, "a b/c*d-_1")  # typed key by key: what is not allowed is dropped
    assert row.alias.text() == "abcd-_1"
    qtbot.keyClicks(row.alias, "wxyz")  # only 10 characters fit
    assert row.alias.text() == "abcd-_1wxy"
    assert lobby.build_config().seats[1].groq_name == "abcd-_1wxy"
    accepted = QValidator.State.Acceptable  # letters of any alphabet are fine, symbols are not
    assert row.alias.validator().validate("zażółć", 0)[0] == accepted
    assert row.alias.validator().validate("a:b", 0)[0] != accepted


def test_model_choice_is_a_closed_list_read_from_a_file(qtbot, tmp_path) -> None:  # type: ignore[no-untyped-def]
    path = _models_file(tmp_path, "a/one", "b/two")
    lobby = LobbyView(models_path=path)
    qtbot.addWidget(lobby)
    row = lobby.rows[1]
    assert not row.model.isEditable()
    assert row.model_names() == ["a/one", "b/two"]
    assert not row.select_model("typed/by/hand") and row.model_name == "a/one"

    row.select_model("b/two")
    path.write_text("# new model below\na/one\nb/two\nc/three\n", encoding="utf-8")
    lobby.refresh()  # as when coming back to the lobby
    assert row.model_names() == ["a/one", "b/two", "c/three"] and row.model_name == "b/two"
    path.write_text("a/one\n", encoding="utf-8")  # the chosen model was removed
    lobby.refresh()
    assert row.model_names() == ["a/one"] and row.model_name == "a/one"


def test_lobby_allows_many_smart_bots_and_hidden_duplicates(qtbot, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(seat_row, "availability_problem", lambda seat: None)
    lobby = LobbyView()
    qtbot.addWidget(lobby)
    assert [r.seat_kind for r in lobby.rows[1:4]] == [SeatKind.SMART] * 3
    assert "wspólną pamięć" not in lobby.message.text()
    lobby.players.setCurrentIndex(0)  # 2 players: seats 2.. are hidden
    lobby.rows[3].kind.setCurrentIndex(2)
    lobby.rows[4].kind.setCurrentIndex(2)
    lobby.rows[4].select_model(lobby.rows[3].model_name)
    assert "wspólną pamięć" not in lobby.message.text()
    lobby.build_config()  # hidden seats are not part of the session


def test_groq_seat_has_a_limited_english_guidelines_field(qtbot, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(seat_row, "availability_problem", lambda seat: None)
    lobby = LobbyView()
    qtbot.addWidget(lobby)
    lobby.show()
    row = lobby.rows[1]
    assert not row.guidelines.isVisible()  # only Groq seats have it
    row.kind.setCurrentIndex(2)
    assert row.guidelines.isVisible() and row.guidelines_label.isVisible()
    assert "po angielsku" in row.guidelines_label.text() and "100" in row.guidelines_label.text()
    assert row.guidelines.maxLength() == 100

    row.guidelines.setText("y" * 150)  # the field refuses more than 100 characters
    assert len(row.guidelines.text()) == 100
    assert row.guidelines_count.text() == "100/100"
    row.guidelines.setText("Avoid hearts.")
    assert lobby.build_config().seats[1].groq_guidelines == "Avoid hearts."
    row.kind.setCurrentIndex(1)  # not Groq any more: the field disappears
    assert not row.guidelines.isVisible()


def test_lobby_hides_seats_beyond_the_player_count(qtbot) -> None:  # type: ignore[no-untyped-def]
    lobby = LobbyView()
    qtbot.addWidget(lobby)
    lobby.show()
    lobby.players.setCurrentIndex(1)  # 3 players
    assert [row.isVisible() for row in lobby.rows] == [True, True, True, False, False]


def test_start_button_emits_the_config(qtbot) -> None:  # type: ignore[no-untyped-def]
    lobby = LobbyView()
    qtbot.addWidget(lobby)
    with qtbot.waitSignal(lobby.startRequested, timeout=1000) as blocker:
        lobby.start_button.click()
    assert isinstance(blocker.args[0], SessionConfig)


# -------------------------------------------------------------- control bar


def test_speed_slider_maps_to_delay_and_max() -> None:
    assert delay_for(0) == MAX_DELAY_S
    assert delay_for(position_for(1.0)) == pytest.approx(1.0)
    assert delay_for(position_for(0.0)) == 0.0


def test_control_bar_drives_pace(qtbot) -> None:  # type: ignore[no-untyped-def]
    pace = PaceControl(1.0)
    bar = ControlBar(pace)
    qtbot.addWidget(bar)
    assert not bar.step_button.isEnabled()
    bar.pause_button.click()
    assert pace.paused
    bar.set_paused(True)
    assert bar.pause_button.text() == "Wznów" and bar.step_button.isEnabled()
    bar.speed.setValue(bar.speed.maximum())
    assert pace.delay == 0.0 and bar.speed_label.text() == "MAX"
    bar.after_trick.setChecked(True)
    assert pace.pause_after_trick


# -------------------------------------------------------------------- game


def test_game_view_plays_a_bot_session_to_the_end(qtbot) -> None:  # type: ignore[no-untyped-def]
    session = SessionController(
        _smart_config(3, deals=2),
        controllers={f"P{i}": SmartHeartsBot(num_samples=0, seed=i) for i in range(3)},
        engine_factory=_factory(1),
    )
    session.pace.delay = 0.0
    view = GameView(session)
    qtbot.addWidget(view)
    session.start()

    qtbot.waitUntil(lambda: view._finished, timeout=8000)
    assert view.status.text().startswith("Koniec gry")
    assert sum(view.scoreboard.totals.values()) == 2 * 26
    assert view.log.count() > 100
    assert view.scoreboard.rowCount() == 3
    session.close()


def test_ui_event_loop_stays_responsive_while_bots_are_slow(qtbot) -> None:  # type: ignore[no-untyped-def]
    class Slow(PlayerController):
        model_name = "slow"

        def select_move(self, observation: PlayerObservation) -> str:
            time.sleep(0.25)
            return observation.legal_moves[0]

    session = SessionController(
        _smart_config(2),
        controllers={"P0": Slow(), "P1": Slow()},
        engine_factory=_factory(1),
    )
    session.pace.delay = 0.0
    view = GameView(session)
    qtbot.addWidget(view)

    gaps: list[float] = []
    last = [time.monotonic()]

    def tick() -> None:
        now = time.monotonic()
        gaps.append(now - last[0])
        last[0] = now

    ticker = QTimer()
    ticker.setInterval(10)
    ticker.timeout.connect(tick)
    ticker.start()
    session.start()
    qtbot.wait(1500)  # ~6 slow moves
    ticker.stop()

    assert view.log.count() >= 3  # the game is advancing...
    assert max(gaps) < 0.15  # ...and the UI thread never waited for a bot
    session.close()


def test_ui_event_loop_stays_responsive_while_a_bot_burns_cpu(qtbot) -> None:  # type: ignore[no-untyped-def]
    """Pure-Python CPU work (like SmartHeartsBot) competes with the UI for the GIL."""
    previous = sys.getswitchinterval()
    tune_gil()

    class Busy(PlayerController):
        model_name = "busy"

        def select_move(self, observation: PlayerObservation) -> str:
            end = time.perf_counter() + 0.25
            while time.perf_counter() < end:
                sum(i * i for i in range(2000))
            return observation.legal_moves[0]

    session = SessionController(
        _smart_config(2),
        controllers={"P0": Busy(), "P1": Busy()},
        engine_factory=_factory(1),
    )
    session.pace.delay = 0.0
    view = GameView(session)
    qtbot.addWidget(view)
    gaps: list[float] = []
    last = [time.monotonic()]

    def tick() -> None:
        now = time.monotonic()
        gaps.append(now - last[0])
        last[0] = now

    ticker = QTimer()
    ticker.setInterval(10)
    ticker.timeout.connect(tick)
    ticker.start()
    try:
        session.start()
        qtbot.wait(1500)
        ticker.stop()
        assert view.log.count() >= 3
        assert max(gaps) < 0.1
    finally:
        sys.setswitchinterval(previous)
        session.close()


def test_human_clicks_a_legal_card_button(qtbot) -> None:  # type: ignore[no-untyped-def]
    config = SessionConfig(
        (SeatConfig(SeatKind.HUMAN), SeatConfig(SeatKind.SMART, smart_samples=0)),
        log_path=None,
    )
    controllers = {"P0": HumanGuiController(), "P1": SmartHeartsBot(num_samples=0, seed=1)}
    session = SessionController(config, controllers=controllers, engine_factory=_factory(3))
    session.pace.delay = 0.0
    view = GameView(session)
    qtbot.addWidget(view)
    view.resize(1200, 800)
    view.show()
    qtbot.waitExposed(view)
    moves: list[MovePlayed] = []
    session.eventsReady.connect(lambda batch: moves.extend(e for e in batch if isinstance(e, MovePlayed)))
    session.start()

    def playable() -> list[CardItem]:
        return [i for i in view.table_scene.items_by_card.values() if i.legal is True]

    qtbot.waitUntil(lambda: bool(playable()), timeout=3000)
    assert sum(1 for i in view.table_scene.items_by_card.values() if i.face_up) == 26  # own hand
    item = playable()[0]
    point = view.table.mapFromScene(item.scenePos())
    qtbot.mouseClick(view.table.viewport(), Qt.MouseButton.LeftButton, pos=point)  # a real click
    qtbot.waitUntil(lambda: any(m.player_id == "P0" and m.card == item.code for m in moves), timeout=3000)
    session.close()


def test_controller_error_dialog_choice_reaches_the_runner(qtbot, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    class Boom(PlayerController):
        model_name = "boom"
        calls = 0

        def select_move(self, observation: PlayerObservation) -> str:
            Boom.calls += 1
            if Boom.calls == 1:
                raise RuntimeError("no key")
            return observation.legal_moves[0]

    session = SessionController(
        _smart_config(2),
        controllers={"P0": Boom(), "P1": SmartHeartsBot(num_samples=0, seed=1)},
        engine_factory=_factory(1),
    )
    session.pace.delay = 0.0
    view = GameView(session)
    qtbot.addWidget(view)
    monkeypatch.setattr(
        GameView, "_ask_error_resolution",
        lambda self, error: self.session.resolve_error(ErrorResolution.RETRY),
    )
    session.start()
    qtbot.waitUntil(lambda: view._finished, timeout=8000)
    assert "Przerwano" not in view.status.text()
    session.close()


# ---------------------------------------------------------------- main window


def test_main_window_switches_between_lobby_and_game(qtbot, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    window = MainWindow()
    qtbot.addWidget(window)
    window.start_session(_smart_config(2, deals=50))
    assert window.stack.currentWidget() is window.game
    session = window.session
    assert session is not None
    qtbot.waitUntil(lambda: session.runner.running, timeout=2000)

    window.show_lobby()
    assert window.stack.currentWidget() is window.lobby
    assert window.session is None and window.game is None
    assert session.runner.join(5.0)  # abort really stops the worker thread
    assert not session.runner.running
