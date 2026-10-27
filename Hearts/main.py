"""Kierki polskie (King): liczba graczy, kontroler przy każdym miejscu, symulacja gdy nie ma człowieka."""

from __future__ import annotations

import sys
from collections.abc import Mapping
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))

from controllers.base import PlayerController
from controllers.ai_bot import PROVIDERS, AIBot
from controllers.human_cli import HumanCLIController
from controllers.smart_bot import SmartHeartsBot
from engine.state import GameState
from evaluation.report import evaluate_log, format_report
from utils.contract_text import contract_label, session_heading
from utils.icl_logger import ICLLogger

PLAYER_COUNTS = (3, 4)
QUALITY_MODE = 0  # entering 0 players runs the quality report instead of a game
SAMPLES = 40
LOG_PATH = ROOT / "logs" / "trajectories.jsonl"
# Players left out of the quality report (the "model" field in trajectories.jsonl).
# Remove a name to include it, e.g. IGNORED_PLAYERS = ("smart_bot",) rates the human too.
IGNORED_PLAYERS: tuple[str, ...] = ("human", "smart_bot")

# (key, label) shown once per seat.
CONTROLLER_CHOICES: tuple[tuple[str, str], ...] = (
    ("human", "Człowiek"),
    ("smart", "SmartHeartsBot"),
    *((provider.id, f"AIBot ({provider.label})") for provider in PROVIDERS.values()),
)


def play_match(
    state: GameState,
    controllers: Mapping[str, PlayerController],
    logger: ICLLogger,
    *,
    show_play: bool,
) -> dict[str, int]:
    """Play a match to the end (every remaining deal). Returns the penalty totals."""
    state.auto_advance = False  # keep a finished deal on the table until it is printed
    while True:
        if show_play:
            _show_deal_start(state)
        while not (state.deal_finished or state.is_over):
            player_id = state.current_player
            assert player_id is not None
            observation = state.get_player_observation(player_id)
            if show_play and not observation.current_trick:
                print()
            controller = controllers[player_id]
            chosen = controller.select_move(observation)
            if chosen not in observation.legal_moves:
                raise ValueError(f"{player_id} chose illegal move {chosen!r}")
            logger.log(observation, chosen, controller.last_reasoning, controller.model_name)
            result = state.play_card(player_id, chosen)
            if show_play:
                print(f"  {player_id}: {chosen}", flush=True)
                if result.trick_completed:
                    print(state.trick_history[-1].summary())
        if show_play:
            _show_deal_end(state)
        if state.is_over:
            return dict(state.total_scores)
        state.start_next_deal()


def play_session(
    num_players: int,
    controllers: Mapping[str, PlayerController],
    logger: ICLLogger,
    *,
    matches: int,
    show_play: bool,
    seed: int | None = None,
) -> dict[str, int]:
    """Play ``matches`` independent matches and return the summed penalties."""
    if matches < 1:
        raise ValueError(f"Match count must be positive, got {matches}")
    totals = {f"P{i}": 0 for i in range(num_players)}
    wins = dict(totals)
    ties = 0
    for number in range(1, matches + 1):
        if show_play:
            print(f"\n=== Partia {number} ===")
        match_seed = None if seed is None else seed + number - 1
        state = GameState.new(num_players, seed=match_seed)
        scores = play_match(state, controllers, logger, show_play=show_play)
        for player_id, points in scores.items():
            totals[player_id] += points
        leaders = _leaders(scores)
        if len(leaders) == 1:
            wins[leaders[0]] += 1
        else:
            ties += 1
        if show_play or matches == 1:
            _show_public(scores, totals)
        else:
            print(f"Partia {number}: {_format_scores(scores)}", flush=True)
    if matches > 1 and not show_play:
        _show_batch(totals, wins, ties, matches)
    return totals


def _show_deal_start(state: GameState) -> None:
    print(
        f"\n--- {session_heading(state.deal_number, state.total_deals)}: "
        f"{contract_label(state.current_contract)} (rozdaje {state.declarer}) ---"
    )
    print("Ręce:")
    for pid in state.player_ids:
        hand = " ".join(state.get_player_observation(pid).hand)
        print(f"  {pid}: {hand}")


def _show_deal_end(state: GameState) -> None:
    print("\nKary w rozdaniu: " + _format_scores(state.scores))
    print("Suma w grze:    " + _format_scores(state.total_scores))


def _format_scores(scores: Mapping[str, int]) -> str:
    return "  ".join(f"{pid}={pts}" for pid, pts in scores.items())


def _leaders(scores: Mapping[str, int]) -> list[str]:
    best = min(scores.values())
    return [pid for pid, pts in scores.items() if pts == best]


def _show_public(scores: dict[str, int], totals: dict[str, int]) -> None:
    print("\n" + "=" * 64)
    print("Partia:   " + _format_scores(scores))
    print("Suma:     " + _format_scores(totals))
    print("Prowadzi: " + ", ".join(_leaders(totals)))


def _show_batch(
    totals: dict[str, int],
    wins: dict[str, int],
    ties: int,
    matches: int,
) -> None:
    print("\n" + "=" * 64)
    print("Suma:     " + _format_scores(totals))
    averages = "  ".join(f"{pid}={totals[pid] / matches:.1f}" for pid in totals)
    print("Średnia:  " + averages)
    print("Wygrane:  " + _format_scores(wins) + f"  remisy={ties}")
    print("Prowadzi: " + ", ".join(_leaders(totals)))


def _ask_players() -> int:
    options = ", ".join(str(n) for n in PLAYER_COUNTS)
    while True:
        raw = input(f"Liczba graczy ({options}; {QUALITY_MODE} = ocena jakości botów z logu): ").strip()
        if raw.isdigit() and int(raw) in (QUALITY_MODE, *PLAYER_COUNTS):
            return int(raw)
        print(f"Podaj jedną z liczb: {QUALITY_MODE}, {options}.")


def run_quality_report(
    log_path: Path = LOG_PATH,
    ignored: tuple[str, ...] = IGNORED_PLAYERS,
) -> bool:
    """Print bot quality computed from the trajectory log. False when there is no log."""
    if not log_path.is_file():
        print(f"Brak logu {log_path}. Najpierw rozegraj kilka partii.")
        return False
    print(format_report(evaluate_log(log_path, ignored)))
    return True


def _ask_kind(player_id: str) -> str:
    print(f"\nKontroler dla {player_id}:")
    for index, (_, label) in enumerate(CONTROLLER_CHOICES, start=1):
        print(f"  [{index}] {label}")
    while True:
        raw = input("Wybierz: ").strip()
        if raw.isdigit() and 1 <= int(raw) <= len(CONTROLLER_CHOICES):
            return CONTROLLER_CHOICES[int(raw) - 1][0]
        print(f"Podaj numer od 1 do {len(CONTROLLER_CHOICES)}.")


def _ask_match_count() -> int:
    while True:
        raw = input("Ile gier zasymulować? Każda gra to 7 rozdań. ").strip()
        if raw.isdigit() and int(raw) >= 1:
            return int(raw)
        print("Podaj dodatnią liczbę całkowitą.")


def _make_controller(kind: str, player_id: str, seat: int) -> PlayerController:
    if kind == "human":
        return HumanCLIController()
    if kind == "smart":
        return SmartHeartsBot(num_samples=SAMPLES, seed=seat)
    if kind in PROVIDERS:  # the choice key is the provider id
        return AIBot(player_id, provider=kind)
    raise ValueError(f"Unknown controller: {kind!r}")


def setup_match(
    num_players: int | None = None,
) -> tuple[int, dict[str, PlayerController], int, bool]:
    """Ask for the table, then for a match count when every seat is a bot."""
    if num_players is None:
        num_players = _ask_players()
    kinds = [_ask_kind(f"P{i}") for i in range(num_players)]
    controllers = {
        f"P{i}": _make_controller(kinds[i], f"P{i}", i) for i in range(num_players)
    }
    labels = dict(CONTROLLER_CHOICES)
    print()
    for player_id, kind in zip(controllers, kinds, strict=True):
        print(f"{player_id}: {labels[kind]}")
    if "human" in kinds:
        return num_players, controllers, 1, False
    matches = _ask_match_count()
    print(f"Gier: {matches}")
    return num_players, controllers, matches, matches == 1


def main() -> None:
    chosen_players = _ask_players()
    if chosen_players == QUALITY_MODE:
        run_quality_report()
        return
    num_players, controllers, matches, show_play = setup_match(chosen_players)
    totals = play_session(
        num_players,
        controllers,
        ICLLogger(LOG_PATH),
        matches=matches,
        show_play=show_play,
    )
    best = min(totals.values())
    winners = [pid for pid, pts in totals.items() if pts == best]
    label = "Wygrana" if len(winners) == 1 else "Remis"
    print(f"\n{label}: {', '.join(winners)} ({best} pkt)")


if __name__ == "__main__":
    main()
