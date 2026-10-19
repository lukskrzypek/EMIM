"""A random controller plays one full deal; every move is logged."""

from __future__ import annotations

import json
import random
from pathlib import Path

from controllers.base import PlayerController
from engine.game import HeartsGameEngine, PlayerObservation
from utils.icl_logger import ICLLogger


class RandomController(PlayerController):
    """Picks a legal card uniformly."""

    def __init__(self, rng: random.Random) -> None:
        self._rng = rng

    def select_move(self, observation: PlayerObservation) -> str:
        return self._rng.choice(observation.legal_moves)


def test_random_full_deal_is_logged(tmp_path: Path) -> None:
    engine = HeartsGameEngine(4, seed=1)
    rng = random.Random(1)
    controllers = {pid: RandomController(rng) for pid in engine.player_ids}
    log_path = tmp_path / "trajectories.jsonl"
    logger = ICLLogger(log_path)

    played = 0
    while not engine.is_over:
        player_id = engine.current_player
        assert player_id is not None
        observation = engine.get_player_observation(player_id)
        chosen = controllers[player_id].select_move(observation)
        assert chosen in observation.legal_moves
        logger.log(observation, chosen)
        engine.play_card(player_id, chosen)
        played += 1

    scores = engine.final_scores
    assert scores is not None
    assert sum(scores.values()) in {26, 26 * (engine.num_players - 1)}
    assert played == 52

    lines = log_path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == played
    for line in lines:
        record = json.loads(line)
        assert list(record) == [
            "player_id",
            "prompt_context",
            "legal_moves",
            "chosen_move",
            "reasoning",
        ]
        assert record["chosen_move"] in record["legal_moves"]
        assert record["prompt_context"]
        assert record["reasoning"] == ""
