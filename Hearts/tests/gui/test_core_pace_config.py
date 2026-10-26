"""PaceControl, HumanGuiController, session bookkeeping and config validation."""

from __future__ import annotations

import threading
import time

import pytest

from engine.game import HeartsGameEngine
from gui.core.controllers_factory import availability_problem, build_controller
from gui.core.human_controller import HumanGuiController, MoveCancelled
from gui.core.pace import PaceControl
from gui.core.seat_config import SeatConfig, SeatKind, SessionConfig, duplicate_ai_memories
from gui.core.session import SessionStats, leaders
from gui.core.snapshot import snapshot_from_engine


# ---------------------------------------------------------------------- pace


def test_gate_before_passes_when_running() -> None:
    assert PaceControl(0).gate_before() is False


def test_gate_before_blocks_until_resume() -> None:
    pace = PaceControl(0, paused=True)
    result: list[bool | None] = []
    thread = threading.Thread(target=lambda: result.append(pace.gate_before()))
    thread.start()
    time.sleep(0.15)
    assert not result
    pace.resume()
    thread.join(1)
    assert result == [False]


def test_step_is_consumed_once_and_ignored_when_running() -> None:
    pace = PaceControl(0)
    pace.step()  # running: no effect
    pace.pause()
    pace.step()
    assert pace.gate_before() is True
    done: list[bool | None] = []
    thread = threading.Thread(target=lambda: done.append(pace.gate_before()), daemon=True)
    thread.start()
    time.sleep(0.15)
    assert not done
    pace.abort()
    thread.join(1)
    assert done == [None]


def test_gate_after_waits_for_the_delay_and_reacts_to_a_new_speed() -> None:
    pace = PaceControl(5.0)
    since = time.monotonic()
    result: list[bool] = []
    thread = threading.Thread(target=lambda: result.append(pace.gate_after(since)))
    thread.start()
    time.sleep(0.1)
    assert not result
    pace.delay = 0.0  # moving the slider to MAX releases the wait
    thread.join(1)
    assert result == [True]


def test_gate_after_skips_the_delay_for_a_step() -> None:
    assert PaceControl(30.0).gate_after(time.monotonic(), stepped=True) is True


def test_trick_hold_returns_at_once_when_paused_or_full_speed() -> None:
    start = time.monotonic()
    assert PaceControl(0).trick_hold()
    assert PaceControl(30.0, paused=True).trick_hold()
    assert time.monotonic() - start < 0.2


def test_on_change_fires_only_when_pause_flips() -> None:
    seen: list[bool] = []
    pace = PaceControl(0, on_change=seen.append)
    pace.pause()
    pace.pause()
    pace.resume()
    assert seen == [True, False]


def test_after_trick_pauses_only_when_requested() -> None:
    pace = PaceControl(0)
    pace.after_trick()
    assert not pace.paused
    pace.pause_after_trick = True
    pace.after_trick()
    assert pace.paused


# --------------------------------------------------------------------- human


def _observation():  # type: ignore[no-untyped-def]
    engine = HeartsGameEngine(4, seed=1)
    return engine.get_player_observation(engine.current_player)


def test_human_controller_returns_the_submitted_card() -> None:
    controller = HumanGuiController(poll_interval=0.01)
    obs = _observation()
    result: list[str] = []
    thread = threading.Thread(target=lambda: result.append(controller.select_move(obs)))
    thread.start()
    deadline = time.monotonic() + 2
    while not controller.awaiting_move and time.monotonic() < deadline:
        time.sleep(0.005)
    assert not controller.submit("9S" if "9S" not in obs.legal_moves else "ZZ")
    assert controller.submit(obs.legal_moves[0])
    thread.join(2)
    assert result == [obs.legal_moves[0]]
    assert not controller.awaiting_move


def test_human_controller_cancel_raises() -> None:
    controller = HumanGuiController(poll_interval=0.01)
    errors: list[BaseException] = []

    def wait() -> None:
        try:
            controller.select_move(_observation())
        except MoveCancelled as exc:
            errors.append(exc)

    thread = threading.Thread(target=wait)
    thread.start()
    time.sleep(0.05)
    controller.cancel()
    thread.join(2)
    assert len(errors) == 1


# ------------------------------------------------------------ session & config


def test_leaders_and_stats() -> None:
    assert leaders({"P0": 3, "P1": 1, "P2": 1}) == ["P1", "P2"]
    stats = SessionStats(("P0", "P1", "P2"))
    stats.record({"P0": 0, "P1": 10, "P2": 16})
    stats.record({"P0": 5, "P1": 5, "P2": 16})
    assert stats.totals == {"P0": 5, "P1": 15, "P2": 32}
    assert stats.wins == {"P0": 1, "P1": 0, "P2": 0} and stats.ties == 1
    assert stats.leaders == ["P0"]
    assert stats.averages["P1"] == 7.5


def test_session_config_validation() -> None:
    seat = SeatConfig(SeatKind.SMART)
    with pytest.raises(ValueError):
        SessionConfig((seat,))
    with pytest.raises(ValueError):
        SessionConfig((seat, seat), deals=0)
    config = SessionConfig((SeatConfig(SeatKind.HUMAN), seat, SeatConfig(SeatKind.HUMAN)))
    assert config.player_ids == ("P0", "P1", "P2")
    assert config.human_ids == ("P0", "P2") and config.has_human
    assert not SessionConfig((seat, seat)).has_human


def test_factory_builds_each_kind(tmp_path) -> None:  # type: ignore[no-untyped-def]
    from controllers.ai_bot import AIBot
    from controllers.smart_bot import SmartHeartsBot

    assert isinstance(build_controller(SeatConfig(SeatKind.HUMAN), "P0", 0), HumanGuiController)
    assert isinstance(build_controller(SeatConfig(SeatKind.SMART), "P1", 1), SmartHeartsBot)
    ai_bot = build_controller(
        SeatConfig(SeatKind.AI, ai_model="m/x"), "P2", 2, trajectories_path=None
    )
    assert isinstance(ai_bot, AIBot) and ai_bot.player_id == "P2" and ai_bot.model == "m/x"


def test_one_ai_model_on_two_seats_needs_different_names() -> None:
    a = SeatConfig(SeatKind.AI, ai_model="openai/gpt-oss-20b")
    b = SeatConfig(SeatKind.AI, ai_model="  OpenAI/GPT-OSS-20B ")
    c = SeatConfig(SeatKind.AI, ai_model="openai/gpt-oss-120b")
    smart = SeatConfig(SeatKind.SMART, ai_model="openai/gpt-oss-20b")  # model unused here
    assert duplicate_ai_memories((a, c, smart)) == []
    assert duplicate_ai_memories((a, b, c)) == ["openai/gpt-oss-20b"]  # one memory file for both
    SessionConfig((a, c, smart, smart))  # many SmartHeartsBots are fine
    with pytest.raises(ValueError, match="different names"):
        SessionConfig((a, b))

    named = SeatConfig(SeatKind.AI, ai_model="openai/gpt-oss-20b", ai_name="bold")
    twin = SeatConfig(SeatKind.AI, ai_model="openai/gpt-oss-20b", ai_name="BOLD")
    assert duplicate_ai_memories((a, named)) == []  # one without a name, one with: fine
    SessionConfig((a, named))
    assert duplicate_ai_memories((named, twin)) == ["openai/gpt-oss-20b (bold)"]  # same file
    with pytest.raises(ValueError):
        SessionConfig((named, twin))


def test_seat_name_decides_the_memory_file(tmp_path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    from controllers.ai_bot import memory_filename
    from gui.core.seat_config import clean_name

    plain = SeatConfig(SeatKind.AI, ai_model="openai/gpt-oss-120b")
    named = SeatConfig(SeatKind.AI, ai_model="openai/gpt-oss-120b", ai_name="bold")
    assert memory_filename(plain.memory_key) == "memory_openai_gpt-oss-120b.txt"
    assert memory_filename(named.memory_key) == "memory_openai_gpt-oss-120b_bold.txt"
    assert plain.display_name == "openai/gpt-oss-120b"
    assert named.display_name == "openai/gpt-oss-120b (bold)"
    assert SeatConfig(SeatKind.SMART).display_name == "SmartHeartsBot"

    assert clean_name("  a b/c:d*  ") == "a_b_c_d_"
    assert clean_name("x" * 40) == "x" * 10 and clean_name("zażółć-1") == "zażółć-1"

    monkeypatch.setattr("controllers.ai_bot.DEFAULT_MEMORY_DIR", tmp_path)  # keep logs/ clean
    bot = build_controller(named, "P0", 0, trajectories_path=None)  # the bot gets the name itself
    assert bot.name == "bold" and bot.model_name == "openai/gpt-oss-120b_bold"
    assert bot._memory_path == tmp_path / "memory_openai_gpt-oss-120b_bold.txt"
    assert build_controller(plain, "P1", 1, trajectories_path=None).model_name == "openai/gpt-oss-120b"


def test_model_catalog_reads_a_file_and_falls_back(tmp_path) -> None:  # type: ignore[no-untyped-def]
    from gui.core.model_catalog import FALLBACK_MODELS, load_models, parse_models

    assert parse_models("# c\n\n a/one  # note\nB/Two\nA/ONE\n") == ("a/one", "B/Two")
    path = tmp_path / "models.txt"
    path.write_text("\ufeffx/one\ny/two\n", encoding="utf-8")
    assert load_models(path) == ("x/one", "y/two")
    path.write_text("# nothing here\n", encoding="utf-8")
    assert load_models(path) == FALLBACK_MODELS["groq"]
    assert load_models(tmp_path / "missing.txt") == FALLBACK_MODELS["groq"]
    assert load_models(tmp_path / "missing.txt", "openai") == FALLBACK_MODELS["openai"]


@pytest.mark.parametrize("provider", ["groq", "openai"])
def test_shipped_model_list_is_usable(provider: str) -> None:
    from gui.core.model_catalog import load_models

    models = load_models(provider=provider)
    assert len(models) >= 2 and len({m.casefold() for m in models}) == len(models)


def test_each_provider_has_its_own_model_file_and_key_file() -> None:
    from controllers.ai_bot import PROVIDERS

    assert PROVIDERS["groq"].models_path.name == "groq_models.txt"
    assert PROVIDERS["openai"].models_path.name == "openai_models.txt"
    assert PROVIDERS["groq"].key_path.name == "groq_api_key.txt"
    assert PROVIDERS["openai"].key_path.name == "openai_api_key.txt"


def test_factory_passes_the_provider_to_the_ai_bot() -> None:
    seat = SeatConfig(SeatKind.AI, ai_provider="openai", ai_model="gpt-4o-mini")
    bot = build_controller(seat, "P1", 1, trajectories_path=None)
    assert bot.provider == "openai" and bot.model == "gpt-4o-mini"


def test_factory_passes_guidelines_to_the_ai_bot() -> None:
    from controllers.ai_bot import USER_GUIDELINES

    def bot(**kw):  # type: ignore[no-untyped-def]
        return build_controller(SeatConfig(SeatKind.AI, **kw), "P1", 1, trajectories_path=None)

    assert bot(ai_guidelines="  Take no hearts.  ")._guidelines == "Take no hearts."
    assert bot(ai_guidelines="")._guidelines == USER_GUIDELINES  # empty -> the bot's default
    assert len(bot(ai_guidelines="x" * 500)._guidelines) == 100
    messages = bot(ai_guidelines="Duck early.").build_messages(_observation())
    assert messages[0]["content"].endswith("Duck early.")


def _observation():  # type: ignore[no-untyped-def]
    engine = HeartsGameEngine(3, seed=1)
    return engine.get_player_observation(engine.current_player)


def test_availability_reports_a_missing_key(tmp_path) -> None:  # type: ignore[no-untyped-def]
    assert availability_problem(SeatConfig(SeatKind.SMART)) is None
    for provider in ("groq", "openai"):
        seat = SeatConfig(SeatKind.AI, ai_provider=provider)
        problem = availability_problem(seat, tmp_path / "missing.txt")
        assert problem is not None and provider in problem.lower()
        key = tmp_path / f"{provider}_key.txt"
        key.write_text("sk_x", encoding="utf-8")
        assert availability_problem(seat, key) is None


def test_snapshot_exposes_all_hands_and_legal_moves() -> None:
    engine = HeartsGameEngine(4, seed=1)
    snap = snapshot_from_engine(engine, 1)
    assert set(snap.hands) == {"P0", "P1", "P2", "P3"}
    assert all(len(h) == 13 for h in snap.hands.values())
    assert snap.current_player == engine.current_player and snap.legal_moves == ("2C",)
    assert not snap.current_trick and not snap.game_over and snap.trick_number == 1


# ------------------------------------------------------------ the pause stops the thinking clock


def test_pace_clock_stands_still_while_paused() -> None:
    import time

    from gui.core.pace import PaceControl

    pace = PaceControl(0)
    start = pace.clock()
    time.sleep(0.05)
    assert pace.clock() - start >= 0.045  # runs while playing

    pace.pause()
    frozen = pace.clock()
    time.sleep(0.15)
    assert pace.clock() == pytest.approx(frozen, abs=0.01)  # stopped

    pace.resume()
    time.sleep(0.05)
    assert 0.04 <= pace.clock() - frozen < 0.12  # the 0.15 s pause is not in it


def test_pace_clock_runs_during_a_stepped_move_only() -> None:
    import time

    from gui.core.pace import PaceControl

    pace = PaceControl(0, paused=True)
    before = pace.clock()
    time.sleep(0.08)
    assert pace.clock() == pytest.approx(before, abs=0.01)

    pace.step()
    assert pace.gate_before() is True  # the stepped move is being thought out
    began = pace.clock()
    time.sleep(0.06)
    assert pace.clock() - began >= 0.05

    assert pace.gate_after(time.monotonic(), stepped=True)  # decided: paused again
    stopped = pace.clock()
    time.sleep(0.08)
    assert pace.clock() == pytest.approx(stopped, abs=0.01)


def test_table_model_thinking_timer_follows_the_clock() -> None:
    from gui.core.events import TurnStarted
    from gui.core.snapshot import TableSnapshot
    from gui.core.table_model import TableModel

    now = [100.0]
    model = TableModel(("P0", "P1"), (), clock=lambda: now[0])
    assert model.think_elapsed() is None
    snapshot = TableSnapshot.__new__(TableSnapshot)  # the timer never looks at it
    model.apply(TurnStarted("P1", False, snapshot))
    now[0] += 2.5
    assert model.think_elapsed() == 2.5
    model.apply(TurnStarted("P0", True, snapshot))  # a human: no timer
    assert model.think_elapsed() is None
