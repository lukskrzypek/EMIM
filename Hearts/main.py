"""Kierki: człowiek kontra bot albo symulacja wybrana liczby partii dwóch botów."""

from __future__ import annotations

import sys
from collections.abc import Mapping
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))

from controllers.base import PlayerController
from controllers.human_cli import HumanCLIController
from controllers.smart_bot import SmartHeartsBot
from engine.game import HeartsGameEngine
from utils.icl_logger import ICLLogger

NUM_PLAYERS = 2
SAMPLES = 40
LOG_PATH = ROOT / "logs" / "trajectories.jsonl"


def play_deal(
    engine: HeartsGameEngine,
    controllers: Mapping[str, PlayerController],
    logger: ICLLogger,
    *,
    show_play: bool,
) -> dict[str, int]:
    """Play one deal to the end. Scores already include shooting the moon."""
    if show_play:
        print("Ręce:")
        for pid in engine.player_ids:
            hand = " ".join(engine.get_player_observation(pid).hand)
            print(f"  {pid}: {hand}")

    while not engine.is_over:
        player_id = engine.current_player
        assert player_id is not None
        observation = engine.get_player_observation(player_id)
        if show_play and not observation.current_trick:
            print()
        chosen = controllers[player_id].select_move(observation)
        if chosen not in observation.legal_moves:
            raise ValueError(f"{player_id} chose illegal move {chosen!r}")
        logger.log(observation, chosen)
        result = engine.play_card(player_id, chosen)
        if show_play:
            print(f"  {player_id}: {chosen}", flush=True)
            if result.trick_completed:
                history = engine.get_player_observation(player_id).trick_history[-1]
                print(history)

    scores = engine.final_scores
    assert scores is not None
    return scores


def play_session(
    num_players: int,
    controllers: Mapping[str, PlayerController],
    logger: ICLLogger,
    *,
    deals: int,
    show_play: bool,
) -> dict[str, int]:
    """Play ``deals`` independent deals and return summed scores."""
    if deals < 1:
        raise ValueError(f"Deal count must be positive, got {deals}")
    totals = {f"P{i}": 0 for i in range(num_players)}
    wins = dict(totals)
    ties = 0
    for deal in range(1, deals + 1):
        if show_play:
            print(f"\n=== Rozdanie {deal} ===")
        engine = HeartsGameEngine(num_players)
        scores = play_deal(engine, controllers, logger, show_play=show_play)
        for player_id, points in scores.items():
            totals[player_id] += points
        leaders = _leaders(scores)
        if len(leaders) == 1:
            wins[leaders[0]] += 1
        else:
            ties += 1
        if show_play or deals == 1:
            _show_public(engine.shot_the_moon, scores, totals)
        else:
            moon = f"  księżyc:{engine.shot_the_moon}" if engine.shot_the_moon else ""
            print(f"Partia {deal}: {_format_scores(scores)}{moon}", flush=True)
    if deals > 1 and not show_play:
        _show_batch(totals, wins, ties, deals)
    return totals


def _format_scores(scores: Mapping[str, int]) -> str:
    return "  ".join(f"{pid}={pts}" for pid, pts in scores.items())


def _leaders(scores: Mapping[str, int]) -> list[str]:
    best = min(scores.values())
    return [pid for pid, pts in scores.items() if pts == best]


def _show_public(
    moon: str | None,
    deal_scores: dict[str, int],
    totals: dict[str, int],
) -> None:
    print("\n" + "=" * 64)
    if moon is not None:
        print(f"{moon} zebrał wszystkie 26 punktów (shooting the moon).")
    print("Rozdanie: " + _format_scores(deal_scores))
    print("Suma:     " + _format_scores(totals))
    print("Prowadzi: " + ", ".join(_leaders(totals)))


def _show_batch(
    totals: dict[str, int],
    wins: dict[str, int],
    ties: int,
    deals: int,
) -> None:
    print("\n" + "=" * 64)
    print("Suma:     " + _format_scores(totals))
    averages = "  ".join(f"{pid}={totals[pid] / deals:.1f}" for pid in totals)
    print("Średnia:  " + averages)
    print("Wygrane:  " + _format_scores(wins) + f"  remisy={ties}")
    print("Prowadzi: " + ", ".join(_leaders(totals)))


def _ask_yes_no(prompt: str) -> bool:
    while True:
        raw = input(prompt).strip().lower()
        if raw in {"t", "tak", "y", "yes"}:
            return True
        if raw in {"n", "nie", "no"}:
            return False
        print("Wpisz t albo n.")


def _ask_deal_count() -> int:
    while True:
        raw = input("Ile partii zasymulować? ").strip()
        if raw.isdigit() and int(raw) >= 1:
            return int(raw)
        print("Podaj dodatnią liczbę całkowitą.")


def main() -> None:
    print(f"Kierki: {NUM_PLAYERS} graczy, SmartHeartsBot ({SAMPLES} losowań Monte Carlo)")
    human_plays = _ask_yes_no("Czy grasz w tej partii? [t/n]: ")
    if human_plays:
        controllers: dict[str, PlayerController] = {
            "P0": HumanCLIController(),
            "P1": SmartHeartsBot(num_samples=SAMPLES, seed=1),
        }
        print("P0: Ty    P1: SmartHeartsBot")
        deals = 1
        show_play = False
    else:
        deals = _ask_deal_count()
        controllers = {
            f"P{i}": SmartHeartsBot(num_samples=SAMPLES, seed=i) for i in range(NUM_PLAYERS)
        }
        print(f"P0 i P1: SmartHeartsBot, partii: {deals}")
        show_play = deals == 1
    totals = play_session(
        NUM_PLAYERS,
        controllers,
        ICLLogger(LOG_PATH),
        deals=deals,
        show_play=show_play,
    )
    best = min(totals.values())
    winners = [pid for pid, pts in totals.items() if pts == best]
    label = "Wygrana" if len(winners) == 1 else "Remis"
    print(f"\n{label}: {', '.join(winners)} ({best} pkt)")


if __name__ == "__main__":
    main()
