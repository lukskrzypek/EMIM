"""A random controller plays one full match; every move is logged."""

from __future__ import annotations

import json
import random
from pathlib import Path

import pytest

from controllers.base import PlayerController
from engine.contracts import CONTRACT_ORDER, contract_total_penalty
from engine.observation import PlayerObservation
from engine.state import GameState
from utils.icl_logger import ICLLogger


class RandomController(PlayerController):
    """Picks a legal card uniformly."""

    def __init__(self, rng: random.Random) -> None:
        self._rng = rng

    def select_move(self, observation: PlayerObservation) -> str:
        return self._rng.choice(observation.legal_moves)


@pytest.mark.parametrize("players", [3, 4])
def test_random_full_match_is_logged(tmp_path: Path, players: int) -> None:
    state = GameState.new(players, seed=1)
    rng = random.Random(1)
    controllers = {pid: RandomController(rng) for pid in state.player_ids}
    log_path = tmp_path / "trajectories.jsonl"
    logger = ICLLogger(log_path)

    played = 0
    while not state.is_over:
        player_id = state.current_player
        assert player_id is not None
        observation = state.get_player_observation(player_id)
        chosen = controllers[player_id].select_move(observation)
        assert chosen in observation.legal_moves
        logger.log(observation, chosen)
        state.play_card(player_id, chosen)
        played += 1

    scores = state.final_scores
    assert scores is not None
    assert sum(scores.values()) == sum(
        contract_total_penalty(contract, players) * players for contract in CONTRACT_ORDER
    )
    assert played == state.total_deals * state.total_tricks * players

    lines = log_path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == played
    for line in lines:
        record = json.loads(line)
        assert list(record) == [
            "player_id",
            "model",
            "prompt_context",
            "legal_moves",
            "chosen_move",
            "reasoning",
        ]
        assert record["chosen_move"] in record["legal_moves"]
        assert record["prompt_context"].startswith(f"KING {players}p")
        assert record["reasoning"] == ""
        assert record["model"] == "unknown"  # default for controllers without a model_name