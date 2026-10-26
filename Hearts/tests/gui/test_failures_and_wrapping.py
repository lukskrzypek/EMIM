"""AI out-of-tokens detection, wrapped log views, no Qt warning from the quality table."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from PySide6.QtCore import Qt, qInstallMessageHandler
from PySide6.QtWidgets import QMessageBox

from collector import Collector
from controllers.base import PlayerController
from controllers.ai_bot import AIBot
from controllers.smart_bot import SmartHeartsBot
from engine.game import HeartsGameEngine, PlayerObservation
from gui.core.events import BotUnavailable, MovePlayed, Notice, SessionFinished
from gui.core.game_runner import GameRunner
from gui.core.ai_failures import classify_failure
from gui.core.live_evaluator import LiveEvaluator
from gui.core.pace import PaceControl
from gui.core.seat_config import SeatConfig, SeatKind, SessionConfig
from gui.qt.game_view import GameView
from gui.qt.quality.insight_panel import BotInsightPanel
from gui.qt.quality.quality_panel import QualityPanel
from gui.qt.session_controller import SessionController
from gui.qt.table.scoreboard import TrickLogWidget

DAILY = (
    "request failed: Error code: 429 - {'error': {'message': 'Rate limit reached for model "
    "`openai/gpt-oss-120b` in organization `org_x` service tier `on_demand` on tokens per day "
    "(TPD): Limit 200000, Used 199990, Requested 1200. Please try again in 9m. Need more tokens? "
    "Upgrade to Dev Tier today at https://console.groq.com/settings/billing', "
    "'type': 'tokens', 'code': 'rate_limit_exceeded'}}"
)
PER_MINUTE = (
    "request failed: Error code: 429 - {'error': {'message': 'Rate limit reached for model "
    "`openai/gpt-oss-120b` on tokens per minute (TPM): Limit 8000, Used 7900, Requested 900. "
    "Please try again in 2.1s. Need more tokens? Upgrade to Dev Tier today at "
    "https://console.groq.com/settings/billing', 'type': 'tokens', 'code': 'rate_limit_exceeded'}}"
)
NO_MODEL = (
    "request failed: Error code: 404 - {'error': {'message': 'The model `openai/gpt-oss-120` "
    "does not exist or you do not have access to it.', 'code': 'model_not_found'}}"
)

# What the OpenAI SDK raises (str(exc) is "Error code: <status> - <body>").
OPENAI_QUOTA = (
    "request failed: Error code: 429 - {'error': {'message': 'You exceeded your current quota, please "
    "check your plan and billing details. For more information on this error, read the docs: "
    "https://platform.openai.com/docs/guides/error-codes/api-errors.', 'type': 'insufficient_quota', "
    "'param': None, 'code': 'insufficient_quota'}}"
)
OPENAI_HARD_LIMIT = (
    "request failed: Error code: 400 - {'error': {'message': 'Billing hard limit has been reached', "
    "'type': 'invalid_request_error', 'code': 'billing_hard_limit_reached'}}"
)
OPENAI_RATE = (
    "request failed: Error code: 429 - {'error': {'message': 'Rate limit reached for gpt-4o in "
    "organization org-x on requests per min (RPM): Limit 3, Used 3, Requested 1. Please try again in "
    "20s.', 'type': 'requests', 'param': None, 'code': 'rate_limit_exceeded'}}"
)
OPENAI_BAD_KEY = (
    "request failed: Error code: 401 - {'error': {'message': 'Incorrect API key provided: sk-abc. You "
    "can find your API key at https://platform.openai.com/account/api-keys.', "
    "'type': 'invalid_request_error', 'param': None, 'code': 'invalid_api_key'}}"
)
OPENAI_NO_MODEL = (
    "request failed: Error code: 404 - {'error': {'message': 'The model `gpt-9` does not exist or you "
    "do not have access to it.', 'type': 'invalid_request_error', 'param': None, 'code': 'model_not_found'}}"
)
OPENAI_PROJECT_DENIED = (
    "request failed: Error code: 403 - {'error': {'message': 'Project `proj_x` does not have access to "
    "model `gpt-5`', 'type': 'invalid_request_error', 'param': None, 'code': 'model_not_found'}}"
)


def _factory(seed: int):  # type: ignore[no-untyped-def]
    return lambda n, k: HeartsGameEngine(n, seed=seed + k)


class FailsFrom(PlayerController):
    """Plays the first legal card, but its ``call``-th request fails with ``reasoning``."""

    model_name = "flaky"

    def __init__(self, call: int, reasoning: str, *, forever: bool = True) -> None:
        self.call, self.reasoning, self.forever = call, reasoning, forever
        self.calls = 0

    def select_move(self, observation: PlayerObservation) -> str:
        self.calls += 1
        failed = self.calls == self.call or (self.forever and self.calls > self.call)
        self.last_reasoning = self.reasoning if failed else "fine"
        return observation.legal_moves[0]


def _config(n: int = 2) -> SessionConfig:
    return SessionConfig(tuple(SeatConfig(SeatKind.AI if i == 0 else SeatKind.SMART,
                                          ai_model="m/x", smart_samples=0) for i in range(n)),
                         log_path=None)


def _run(controller: PlayerController) -> Collector:
    sink = Collector()
    runner = GameRunner(
        _config(), sink, pace=PaceControl(0),
        controllers={"P0": controller, "P1": SmartHeartsBot(num_samples=0, seed=1)},
        engine_factory=_factory(4),
    )
    runner.start()
    sink.wait_finished()
    return sink


# ------------------------------------------------------------------ classify


def test_classify_tells_tokens_access_and_rate_limits_apart() -> None:
    assert classify_failure(DAILY).kind == "tokens" and classify_failure(DAILY).fatal
    assert classify_failure(NO_MODEL).kind == "access" and classify_failure(NO_MODEL).fatal
    rate = classify_failure(PER_MINUTE)
    assert rate.kind == "rate" and not rate.fatal  # waiting a few seconds is enough
    assert "TPD" in classify_failure(DAILY).message
    for text in (None, "", "fine", "I will duck. request failed: later", "request failed: boom"):
        assert classify_failure(text) is None


@pytest.mark.parametrize(
    ("text", "kind"),
    [
        (OPENAI_QUOTA, "tokens"),  # a 429, but waiting does not bring the credit back
        (OPENAI_HARD_LIMIT, "tokens"),
        (OPENAI_BAD_KEY, "access"),
        (OPENAI_NO_MODEL, "access"),
        (OPENAI_PROJECT_DENIED, "access"),
        (OPENAI_RATE, "rate"),
    ],
)
def test_classify_understands_openai_errors(text: str, kind: str) -> None:
    failure = classify_failure(text)
    assert failure is not None and failure.kind == kind and failure.fatal == (kind != "rate")


def test_a_real_openai_bot_with_no_credit_stops_the_game() -> None:
    def refuse(**_kw):  # type: ignore[no-untyped-def]
        raise RuntimeError(OPENAI_QUOTA.removeprefix("request failed: "))

    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=refuse)))
    bot = AIBot(
        "P0", provider="openai", client=client,
        exchange_log_path="", illegal_log_path="", api_error_log_path="", memory_path=None,
    )
    sink = _run(bot)
    assert sink.of(BotUnavailable)[0].reason == "tokens"
    assert sink.wait_finished().aborted


# -------------------------------------------------------------------- runner


def test_game_ends_when_the_tokens_run_out() -> None:
    bot = FailsFrom(call=3, reasoning=DAILY)
    sink = _run(bot)
    unavailable = sink.of(BotUnavailable)
    assert len(unavailable) == 1
    assert unavailable[0].player_id == "P0" and unavailable[0].reason == "tokens"
    assert "TPD" in unavailable[0].message
    assert sink.wait_finished().aborted
    assert len([m for m in sink.of(MovePlayed) if m.player_id == "P0"]) == 2  # the failed one isn't played
    assert bot.calls == 3  # and nobody asks again


def test_game_ends_on_a_model_that_does_not_exist() -> None:
    sink = _run(FailsFrom(call=1, reasoning=NO_MODEL))
    assert sink.of(BotUnavailable)[0].reason == "access"
    assert sink.wait_finished().aborted
    assert not [m for m in sink.of(MovePlayed) if m.player_id == "P0"]


def test_a_per_minute_limit_only_warns() -> None:
    sink = _run(FailsFrom(call=2, reasoning=PER_MINUTE, forever=False))
    assert not sink.of(BotUnavailable)
    assert not sink.wait_finished().aborted
    assert any("limit" in n.text for n in sink.of(Notice))


def test_a_real_ai_bot_with_no_tokens_stops_the_game() -> None:
    def refuse(**_kw):  # type: ignore[no-untyped-def]
        raise RuntimeError(DAILY.removeprefix("request failed: "))

    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=refuse)))
    bot = AIBot("P0", client=client, exchange_log_path="", illegal_log_path="", api_error_log_path="", memory_path=None)
    sink = _run(bot)
    assert sink.of(BotUnavailable)[0].reason == "tokens"
    assert sink.wait_finished().aborted


# ------------------------------------------------------------------------ Qt


def test_game_view_tells_the_user_the_tokens_are_gone(qtbot, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    shown: list[str] = []
    monkeypatch.setattr(QMessageBox, "exec", lambda self: shown.append(self.text()) or 0)
    session = SessionController(
        _config(),
        controllers={"P0": FailsFrom(3, DAILY), "P1": SmartHeartsBot(num_samples=0, seed=1)},
        engine_factory=_factory(4),
    )
    session.pace.delay = 0.0
    view = GameView(session)
    qtbot.addWidget(view)
    session.start()
    qtbot.waitUntil(lambda: bool(shown), timeout=8000)
    assert "nie może dalej grać" in shown[0] and "tokenów" in shown[0] and "zakończona" in shown[0]
    box = view.last_failure_box
    assert box is not None and "tokeny" in box.windowTitle() and "TPD" in box.informativeText()
    qtbot.waitUntil(lambda: view._finished, timeout=3000)
    log = [view.log.item(i).text() for i in range(view.log.count())]
    assert any("Gra zakończona" in line for line in log)
    session.close()


def test_log_lists_wrap_long_lines(qtbot) -> None:  # type: ignore[no-untyped-def]
    log = TrickLogWidget()
    qtbot.addWidget(log)
    insight = BotInsightPanel({"P0": "Bot"}, human_ids=())
    qtbot.addWidget(insight)
    for view in (log, insight.entries):
        assert view.wordWrap()
        assert view.horizontalScrollBarPolicy() == Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        assert view.textElideMode() == Qt.TextElideMode.ElideNone


def test_refreshing_the_quality_table_makes_qt_complain_about_nothing(qtbot) -> None:  # type: ignore[no-untyped-def]
    messages: list[str] = []
    previous = qInstallMessageHandler(lambda kind, ctx, text: messages.append(text))
    try:
        panel = QualityPanel({"P0": "A", "P1": "B"}, has_human=False, evaluator=LiveEvaluator())
        qtbot.addWidget(panel)
        for _ in range(3):
            panel.refresh()
    finally:
        qInstallMessageHandler(previous)
    assert panel.table.rowCount() == 2 and panel.table.item(0, 0) is not None
    assert not [m for m in messages if "already owned" in m], messages


# ------------------------------------------------------- memory in the stats panel


def _move(player: str) -> MovePlayed:
    return MovePlayed(1, 1, player, "2C", "m", 0.1, "", None, None)  # type: ignore[arg-type]


def test_quality_panel_shows_the_memory_of_every_ai_bot(qtbot) -> None:  # type: ignore[no-untyped-def]
    files = {"m/a": "plan A", "m/b": "plan B"}
    panel = QualityPanel(
        {"P0": "Człowiek", "P1": "m/a", "P2": "m/b"}, has_human=True, evaluator=None,
        memory_models={"P1": "m/a", "P2": "m/b"}, memory_reader=files.__getitem__,
    )
    qtbot.addWidget(panel)
    panel.show()
    board = panel.memory_board
    assert board.isVisible() and set(board.pads) == {"P1", "P2"}  # no pad for the human
    assert board.pads["P1"].toPlainText() == "plan A" and board.pads["P2"].toPlainText() == "plan B"
    assert "P1" in board.headers["P1"].text() and "m/a" in board.headers["P1"].text()
    assert board.pads["P1"].isReadOnly()

    files["m/a"] = "plan A, revised"  # the bot rewrote its pad while moving
    files["m/b"] = "plan B, revised"
    panel.apply([_move("P1")])
    assert board.pads["P1"].toPlainText() == "plan A, revised"
    assert board.pads["P2"].toPlainText() == "plan B"  # only the seat that moved is re-read
    panel.apply([_move("P0")])  # a human's move touches nothing
    assert board.pads["P2"].toPlainText() == "plan B"
    panel.apply([SessionFinished({}, {}, 0, 0, (), False)])  # the end re-reads everyone
    assert board.pads["P2"].toPlainText() == "plan B, revised"


def test_memory_card_is_hidden_without_ai_bots(qtbot) -> None:  # type: ignore[no-untyped-def]
    panel = QualityPanel({"P0": "A", "P1": "B"}, has_human=False, evaluator=None)
    qtbot.addWidget(panel)
    panel.show()
    assert not panel.memory_board.isVisible() and not panel.memory_board.pads


def test_game_view_gives_the_stats_panel_the_ai_seats(qtbot) -> None:  # type: ignore[no-untyped-def]
    config = SessionConfig(
        (SeatConfig(SeatKind.AI, ai_model="m/a"), SeatConfig(SeatKind.SMART, smart_samples=0),
         SeatConfig(SeatKind.AI, ai_model="m/a", ai_name="twin")),  # same model, own pad
        log_path=None,
    )
    session = SessionController(config, controllers={
        "P0": SmartHeartsBot(num_samples=0, seed=0), "P1": SmartHeartsBot(num_samples=0, seed=1),
        "P2": SmartHeartsBot(num_samples=0, seed=2),
    })
    view = GameView(session)
    qtbot.addWidget(view)
    board = view.quality_panel.memory_board
    assert board.seat_models == {"P0": "m/a", "P2": "m/a_twin"}  # two different memory files
    assert "m/a (twin)" in board.headers["P2"].text() and "(" not in board.headers["P0"].text()
    seats = view.quality_panel.quality.seats
    assert seats["P0"].label == "m/a" and seats["P2"].label == "m/a (twin)"
    session.close()


# ------------------------------------------------- the seat name in the trajectory log


def test_trajectory_log_tells_two_bots_of_one_model_apart(tmp_path) -> None:  # type: ignore[no-untyped-def]
    import json

    def ai(pid: str, name: str = "") -> AIBot:
        reply = SimpleNamespace(content="no card here")  # unparsable: the bot plays its fallback
        client = SimpleNamespace(
            chat=SimpleNamespace(
                completions=SimpleNamespace(create=lambda **_: SimpleNamespace(choices=[SimpleNamespace(message=reply)]))
            )
        )
        return AIBot(
            pid, model="m/x", name=name, client=client, exchange_log_path="", illegal_log_path="", api_error_log_path="",
            memory_path=tmp_path / f"{pid}.txt",
        )

    log = tmp_path / "trajectories.jsonl"
    config = SessionConfig(
        (
            SeatConfig(SeatKind.AI, ai_model="m/x"),  # no name: logged as before
            SeatConfig(SeatKind.AI, ai_model="m/x", ai_name="bold"),
            SeatConfig(SeatKind.SMART, smart_samples=0),
        ),
        log_path=log,
    )
    sink = Collector()
    runner = GameRunner(
        config, sink, pace=PaceControl(0),
        controllers={"P0": ai("P0"), "P1": ai("P1", "bold"), "P2": SmartHeartsBot(num_samples=0, seed=2)},
        engine_factory=_factory(3),
        analyzer=LiveEvaluator(),
    )
    runner.start()
    assert not sink.wait_finished().aborted

    logged = [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]
    by_player = {}
    for record in logged:
        by_player.setdefault(record["player_id"], set()).add(record["model"])
    assert by_player == {"P0": {"m/x"}, "P1": {"m/x_bold"}, "P2": {"smart_bot"}}
    shown = {m.player_id: m.model_name for m in sink.of(MovePlayed)}  # the live panels agree
    assert shown == {"P0": "m/x", "P1": "m/x_bold", "P2": "smart_bot"}
    analysed = {m.player_id: m.analysis.model_name for m in sink.of(MovePlayed) if m.analysis}
    assert analysed.get("P1", "m/x_bold") == "m/x_bold"
