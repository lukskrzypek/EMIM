"""Live evaluator and aggregator: the numbers must equal the offline quality report."""

from __future__ import annotations

from pathlib import Path

import pytest

from collector import Collector
from controllers.base import PlayerController
from controllers.smart_bot import SmartHeartsBot
from engine.game import HeartsGameEngine, PlayerObservation
from evaluation.report import build_report
from evaluation.trajectories import load_moves
from gui.core.events import MovePlayed, SessionFinished, TurnStarted
from gui.core.game_runner import AnalysisInput, GameRunner
from gui.core.live_evaluator import (
    LiveAnalysis,
    LiveEvaluator,
    MoveEval,
    evaluate_position,
    hint_for_table,
    to_engine_code,
)
from gui.core.live_quality import LiveQuality
from gui.core.pace import PaceControl
from gui.core.seat_config import SeatConfig, SeatKind, SessionConfig
from gui.core.table_model import TableModel


class LastLegal(PlayerController):
    """Deliberately naive second 'model', so merging by model is exercised."""

    model_name = "last_legal"

    def select_move(self, observation: PlayerObservation) -> str:
        return observation.legal_moves[-1]


def _play(players: int, seed: int, log: Path | None, deals: int = 1) -> tuple[Collector, GameRunner]:
    controllers: dict[str, PlayerController] = {
        f"P{i}": (LastLegal() if i == 0 else SmartHeartsBot(num_samples=0, seed=i))
        for i in range(players)
    }
    config = SessionConfig(
        tuple(SeatConfig(SeatKind.SMART, smart_samples=0) for _ in range(players)),
        deals=deals,
        log_path=log,
    )
    sink = Collector()
    runner = GameRunner(
        config,
        sink,
        pace=PaceControl(0),
        controllers=controllers,
        analyzer=LiveEvaluator(),
        engine_factory=lambda n, k: HeartsGameEngine(n, seed=seed + k),
    )
    runner.start()
    sink.wait_finished(timeout=30)
    return sink, runner


def test_engine_code_normalisation() -> None:
    assert to_engine_code("10h") == "TH"
    assert to_engine_code("Qs") == "QS"
    assert to_engine_code("2c") == "2C"
    assert to_engine_code("Ad") == "AD"


@pytest.mark.parametrize("players", [2, 3, 4, 5])
def test_live_numbers_equal_the_offline_report(tmp_path: Path, players: int) -> None:
    log = tmp_path / "trajectories.jsonl"
    sink, _ = _play(players, seed=11, log=log, deals=2)

    labels = {f"P{i}": f"seat {i}" for i in range(players)}
    live = LiveQuality(labels)
    for event in sink.of(MovePlayed):
        assert isinstance(event.analysis, LiveAnalysis)
        live.record(event.analysis, event.move_number)

    offline = build_report(load_moves(log)).models
    merged = live.by_model()
    assert set(merged) == set(offline) == {"last_legal", "smart_bot"}
    for name, expected in offline.items():
        got = merged[name]
        assert got.moves == expected.moves
        assert got.forced == expected.forced
        assert got.illegal == expected.illegal
        assert got.decisions == expected.decisions
        assert got.correctness_sum == pytest.approx(expected.correctness_sum)
        assert got.aggressiveness_sum == pytest.approx(expected.aggressiveness_sum)
        assert got.aggressiveness_n == expected.aggressiveness_n
        assert got.verdicts == expected.verdicts
        assert {k: sorted(v) for k, v in got.scenarios.items()} == {
            k: sorted(v) for k, v in expected.scenarios.items()
        }
        assert got.correctness == pytest.approx(expected.correctness)


def test_analysis_describes_the_alternatives() -> None:
    sink, _ = _play(4, seed=5, log=None)
    analyses = [e.analysis for e in sink.of(MovePlayed)]
    assert len(analyses) == 13 * 4
    for event in sink.of(MovePlayed):
        a = event.analysis
        assert a.player_id == event.player_id
        assert a.chosen == event.card  # engine code, not the evaluator's "10h"
        assert a.chosen_eval is not None
        assert len(a.ranking) >= 1
        scores = [m.correctness for m in a.ranking]
        assert scores == sorted(scores, reverse=True)
        assert a.best.correctness == scores[0]
        assert a.regret == pytest.approx(scores[0] - a.chosen_eval.correctness, abs=0.051)
        assert a.rank is not None and a.rank >= 1
        assert (a.regret == 0) == (a.rank == 1)
    # the naive bot picks a worse card than the best one at least once
    assert any(a.regret and a.regret > 0 for a in analyses if a.player_id == "P0")


def test_hint_equals_the_analysis_of_the_same_position() -> None:
    sink, _ = _play(4, seed=3, log=None)
    model = TableModel(("P0", "P1", "P2", "P3"), ())
    hint: LiveAnalysis | None = None
    checked = 0
    for event in sink.events:
        model.apply(event)
        if isinstance(event, TurnStarted):
            hint = hint_for_table(model, event.player_id)  # what a human would be shown
        elif isinstance(event, MovePlayed):
            assert hint is not None
            assert hint.chosen is None and hint.player_id == event.player_id
            assert hint.ranking == event.analysis.ranking
            checked += 1
    assert checked == 13 * 4
    assert len(model.tricks) == 13


def test_hint_is_only_for_the_player_to_move() -> None:
    sink, _ = _play(3, seed=1, log=None)
    model = TableModel(("P0", "P1", "P2"), ())
    first = next(e for e in sink.events if isinstance(e, TurnStarted))
    model.apply(first)
    other = next(p for p in ("P0", "P1", "P2") if p != first.player_id)
    assert hint_for_table(model, first.player_id) is not None
    assert hint_for_table(model, other) is None


def test_disabled_evaluator_is_silent_and_cheap() -> None:
    evaluator = LiveEvaluator()
    engine = HeartsGameEngine(3, seed=2)
    pid = engine.current_player
    obs = engine.get_player_observation(pid)
    data = AnalysisInput(1, obs, (), obs.legal_moves[0], "x")
    assert evaluator(data) is not None
    evaluator.enabled = False
    assert evaluator(data) is None


def test_invalid_position_gives_none() -> None:
    assert (
        evaluate_position(
            player_id="P0",
            deal_number=1,
            hand=["2C"],  # a hand of one card on the first trick is inconsistent
            history=[],
            current_trick=[],
            num_players=4,
            legal_moves=["2C"],
        )
        is None
    )


def _analysis(pid: str, chosen: str, scores: dict[str, float], scenario: str = "lead") -> LiveAnalysis:
    ranking = tuple(
        MoveEval(c, s, "optymalne" if s >= 90 else "niepoprawne", 10.0, "defensywny", scenario)
        for c, s in sorted(scores.items(), key=lambda kv: -kv[1])
    )
    return LiveAnalysis(pid, 1, ranking, chosen, "m")


def test_aggregator_bookkeeping() -> None:
    live = LiveQuality({"P0": "Bot"})
    live.record(_analysis("P0", "AS", {"AS": 100.0, "2C": 50.0}), 1)  # best
    live.record(_analysis("P0", "2C", {"AS": 100.0, "2C": 30.0}), 2)  # regret 70
    live.record(_analysis("P0", "3C", {"3C": 100.0}, scenario="only_move"), 3)  # forced
    seat = live.seat("P0")

    assert seat.stats.moves == 3 and seat.stats.forced == 1 and seat.decisions == 2
    assert seat.correctness == pytest.approx(65.0)
    assert seat.avg_regret == pytest.approx(35.0)
    assert seat.best_rate == pytest.approx(0.5)
    assert seat.verdict_shares() == {"optymalne": 0.5, "poprawne": 0.0, "wątpliwe": 0.0, "niepoprawne": 0.5}
    assert [r.forced for r in seat.records] == [False, False, True]
    assert len(seat.decision_records()) == 2
    assert live.last is not None and live.last.chosen == "3C"
    assert live.total_moves == 3


def test_session_finishes_with_every_move_analysed() -> None:
    sink, _ = _play(5, seed=2, log=None)
    assert not sink.of(SessionFinished)[0].aborted
    assert all(e.analysis is not None for e in sink.of(MovePlayed))
