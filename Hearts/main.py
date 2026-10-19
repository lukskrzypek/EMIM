"""Hotseat Hearts: human controllers, one deal or a match to 100 points."""

from __future__ import annotations

import sys
from collections.abc import Mapping
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))

from controllers.base import PlayerController
from controllers.human_cli import HumanCLIController
from engine.game import HeartsGameEngine
from utils.icl_logger import ICLLogger

MATCH_LIMIT = 100
LOG_PATH = ROOT / "logs" / "trajectories.jsonl"


def play_deal(
    engine: HeartsGameEngine,
    controllers: Mapping[str, PlayerController],
    logger: ICLLogger,
) -> dict[str, int]:
    """Play one deal to the end. Scores already include shooting the moon."""
    while not engine.is_over:
        player_id = engine.current_player
        assert player_id is not None
        observation = engine.get_player_observation(player_id)
        chosen = controllers[player_id].select_move(observation)
        if chosen not in observation.legal_moves:
            raise ValueError(f"{player_id} chose illegal move {chosen!r}")
        logger.log(observation, chosen)
        engine.play_card(player_id, chosen)

    scores = engine.final_scores
    assert scores is not None
    return scores


def play_session(
    num_players: int,
    controllers: Mapping[str, PlayerController],
    logger: ICLLogger,
    *,
    to_score: int | None,
) -> dict[str, int]:
    """Play a single deal, or repeat deals until a total reaches ``to_score``."""
    totals = {f"P{i}": 0 for i in range(num_players)}
    deal = 1
    while True:
        print(f"\n=== Rozdanie {deal} ===")
        engine = HeartsGameEngine(num_players)
        scores = play_deal(engine, controllers, logger)
        for player_id, points in scores.items():
            totals[player_id] += points
        _show_public(engine.shot_the_moon, scores, totals)
        if to_score is None or max(totals.values()) >= to_score:
            return totals
        deal += 1


def _show_public(
    moon: str | None,
    deal_scores: dict[str, int],
    totals: dict[str, int],
) -> None:
    print("\n" + "=" * 64)
    if moon is not None:
        print(f"{moon} zebrał wszystkie 26 punktów (shooting the moon).")
    print("Rozdanie: " + "  ".join(f"{pid}={pts}" for pid, pts in deal_scores.items()))
    print("Suma:     " + "  ".join(f"{pid}={pts}" for pid, pts in totals.items()))
    best = min(totals.values())
    leaders = [pid for pid, pts in totals.items() if pts == best]
    print("Prowadzi: " + ", ".join(leaders))


def _ask_players() -> int:
    while True:
        raw = input("Liczba graczy (2, 3, 4 lub 5): ").strip()
        if raw in {"2", "3", "4", "5"}:
            return int(raw)
        print("Podaj 2, 3, 4 albo 5.")


def _ask_limit() -> int | None:
    while True:
        raw = input("Tryb: [1] pojedyncze rozdanie  [2] do 100 punktów: ").strip()
        if raw == "1":
            return None
        if raw == "2":
            return MATCH_LIMIT
        print("Wybierz 1 albo 2.")


def main() -> None:
    num_players = _ask_players()
    to_score = _ask_limit()
    controllers = {f"P{i}": HumanCLIController() for i in range(num_players)}
    totals = play_session(num_players, controllers, ICLLogger(LOG_PATH), to_score=to_score)
    best = min(totals.values())
    winners = [pid for pid, pts in totals.items() if pts == best]
    label = "Wygrana" if len(winners) == 1 else "Remis"
    print(f"\n{label}: {', '.join(winners)} ({best} pkt)")


if __name__ == "__main__":
    main()
