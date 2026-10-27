"""PlayerObservation and its ICL prompt (SPEC.md, section 5)."""

from __future__ import annotations

import random
from pathlib import Path

import pytest

from engine.contracts import CONTRACT_ORDER, GameContract
from engine.observation import CONTRACT_RULES, PlayerObservation
from engine.state import GameState


def first_trick_state(contract: GameContract, players: int = 4) -> GameState:
    """Deal of ``contract`` opened by P1."""
    index = CONTRACT_ORDER.index(contract)
    return GameState.new(
        players,
        seed=3,
        first_declarer=(1 - index) % players,
        start_deal=index + 1,
    )


def test_observation_fields_at_the_start_of_a_deal() -> None:
    state = first_trick_state(GameContract.NO_QUEENS)
    obs = state.get_player_observation("P1")
    assert obs.player_id == "P1" and obs.num_players == 4
    assert obs.contract is GameContract.NO_QUEENS and obs.declarer == "P1"
    assert obs.deal_number == 3 and obs.total_deals == 7
    assert obs.trick_number == 1 and obs.total_tricks == 13
    assert obs.current_player == "P1" and not obs.game_over
    assert obs.hand == [str(c) for c in sorted(state.hands["P1"])]
    assert obs.current_trick == [] and obs.trick_history == [] and obs.played_cards == []
    assert obs.legal_moves == obs.hand  # free lead in NO_QUEENS
    assert obs.exposed_voids == {p: [] for p in state.player_ids}
    assert obs.scores == dict.fromkeys(state.player_ids, 0)
    assert obs.total_scores == dict.fromkeys(state.player_ids, 0)


def test_legal_moves_only_for_the_player_on_turn() -> None:
    state = first_trick_state(GameContract.NO_TRICKS)
    assert state.get_player_observation("P2").legal_moves == []
    assert state.get_player_observation("P1").legal_moves != []


def test_observation_hides_other_hands() -> None:
    obs = first_trick_state(GameContract.NO_TRICKS).get_player_observation("P0")
    text = repr(obs)
    assert len(obs.hand) == 13
    assert "hands" not in text


def test_observation_follows_the_play() -> None:
    state = first_trick_state(GameContract.NO_TRICKS)
    rng = random.Random(0)
    for _ in range(5):
        player = state.current_player
        assert player is not None
        state.play_card(player, rng.choice(state.get_legal_moves(player)))
    obs = state.get_player_observation(state.current_player or "P0")
    assert obs.trick_number == 2
    assert len(obs.trick_history) == 1 and obs.trick_history[0].startswith("T1: ")
    assert obs.trick_history[0].endswith("(20pts)")
    assert len(obs.current_trick) == 1
    assert len(obs.played_cards) == 5
    assert [p for p, _ in obs.played_cards] == ["P1", "P2", "P3", "P0", state.trick_history[0].winner]
    assert sum(obs.scores.values()) == 20


@pytest.mark.parametrize("contract", list(CONTRACT_ORDER))
def test_prompt_is_short_and_mentions_the_contract(contract: GameContract) -> None:
    state = first_trick_state(contract)
    prompt = state.get_player_observation("P1").to_icl_prompt()
    lines = prompt.splitlines()
    assert len(lines) <= 20
    assert lines[0] == (
        f"KING 4p | You: P1 | Deal {CONTRACT_ORDER.index(contract) + 1}/7 "
        f"{contract.value} (declarer P1) | Trick 1/13 | Turn: P1"
    )
    assert CONTRACT_RULES[contract] in prompt
    assert any(line.startswith("Hand: ") for line in lines)
    assert "Trick: (empty)" in lines and "History: (none)" in lines
    assert "hearts_broken" not in prompt.lower() and "hearts broken" not in prompt.lower()
    assert "Lowest total wins" in prompt


def test_prompt_lines_stay_bounded_late_in_the_deal() -> None:
    state = GameState.new(3, seed=4, start_deal=1)
    rng = random.Random(2)
    while state.trick_number < 16:
        player = state.current_player
        assert player is not None
        state.play_card(player, rng.choice(state.get_legal_moves(player)))
    prompt = state.get_player_observation(state.current_player or "P0").to_icl_prompt()
    lines = prompt.splitlines()
    assert len(lines) <= 20
    assert "KING 3p" in lines[0] and "Trick 16/17" in lines[0] and "Deal 1/7" in lines[0]
    assert any(line.startswith("History (last 8 of 15):") for line in lines)
    assert prompt.count("-> Win:") == 8


def test_prompt_history_limit_can_be_changed() -> None:
    state = GameState.new(4, seed=4)
    rng = random.Random(1)
    for _ in range(12):
        player = state.current_player
        assert player is not None
        state.play_card(player, rng.choice(state.get_legal_moves(player)))
    obs = state.get_player_observation(state.current_player or "P0")
    assert obs.to_icl_prompt(max_history=2).count("-> Win:") == 2
    assert obs.to_icl_prompt(max_history=0).count("-> Win:") == 0
    assert obs.to_icl_prompt(max_history=10).count("-> Win:") == 3


def test_game_over_prompt() -> None:
    state = GameState.new(4, seed=1, start_deal=7)
    rng = random.Random(1)
    while not state.is_over:
        player = state.current_player
        assert player is not None
        state.play_card(player, rng.choice(state.get_legal_moves(player)))
    obs = state.get_player_observation("P0")
    assert obs.game_over and obs.legal_moves == [] and obs.hand == []
    prompt = obs.to_icl_prompt()
    assert prompt.splitlines()[0] == "KING 4p | You: P0 | GAME OVER"
    assert "Final totals:" in prompt and "Last deal:" in prompt


def test_defaults_allow_a_minimal_observation() -> None:
    obs = PlayerObservation(
        player_id="P0",
        hand=["2C"],
        current_trick=[],
        trick_history=[],
        exposed_voids={"P0": []},
        scores={"P0": 0},
        legal_moves=["2C"],
    )
    assert obs.contract is GameContract.NO_TRICKS and obs.num_players == 4
    assert "Hand: 2C" in obs.to_icl_prompt()

# --------------------------------------------------- log written by ICLLogger


@pytest.mark.parametrize("players", [3, 4])
def test_logged_prompts_are_read_back_by_the_trajectory_loader(
    players: int, tmp_path: Path
) -> None:
    from engine.contracts import GameContract
    from evaluation.trajectories import load_moves
    from utils.icl_logger import ICLLogger

    path = tmp_path / "trajectories.jsonl"
    logger = ICLLogger(path)
    state = GameState.new(players, seed=9, start_deal=2)  # NO_HEARTS, then NO_QUEENS
    rng = random.Random(1)
    logged = 0
    while state.deal_number <= 3:
        player = state.current_player
        assert player is not None
        observation = state.get_player_observation(player)
        chosen = rng.choice(observation.legal_moves)
        logger.log(observation, chosen, "", "m")
        state.play_card(player, chosen)
        logged += 1
    loaded = load_moves(path)
    assert loaded.records == logged and len(loaded.moves) == logged and not loaded.skipped
    assert {m.state.contract for m in loaded.moves} == {
        GameContract.NO_HEARTS,
        GameContract.NO_QUEENS,
    }
    assert all(m.state.num_players == players for m in loaded.moves)
    per_deal = players * (13 if players == 4 else 17)
    assert sum(1 for m in loaded.moves if not m.state.history and not m.state.current_trick) == 2
    assert loaded.moves[per_deal].state.history == []  # the second deal starts a fresh history
