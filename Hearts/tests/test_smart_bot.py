"""Tests for SmartHeartsBot: heuristics, hidden-hand inference, Monte Carlo play."""

from __future__ import annotations

import random

from controllers.base import PlayerController
from controllers.smart_bot import SmartHeartsBot, _build_context, _deal_unknown
from engine.game import HeartsGameEngine, PlayerObservation
from engine.models import Card


def make_obs(
    hand: list[str],
    legal: list[str],
    trick: list[tuple[str, str]] | None = None,
    *,
    history: list[str] | None = None,
    hearts_broken: bool = False,
    trick_number: int = 5,
) -> PlayerObservation:
    return PlayerObservation(
        player_id="P0",
        hand=hand,
        current_trick=trick or [],
        trick_history=history or [],
        exposed_voids={},
        hearts_broken=hearts_broken,
        scores={"P0": 0, "P1": 0, "P2": 0, "P3": 0},
        legal_moves=legal,
        trick_number=trick_number,
        current_player="P0",
    )


def rules_bot() -> SmartHeartsBot:
    """Heuristics only (no simulation)."""
    return SmartHeartsBot(num_samples=0)


class RandomBot(PlayerController):
    def __init__(self, rng: random.Random) -> None:
        self._rng = rng

    def select_move(self, observation: PlayerObservation) -> str:
        return self._rng.choice(observation.legal_moves)


def play_deal(engine: HeartsGameEngine, controllers: dict[str, PlayerController]) -> dict[str, int]:
    while not engine.is_over:
        pid = engine.current_player
        assert pid is not None
        obs = engine.get_player_observation(pid)
        move = controllers[pid].select_move(obs)
        assert move in obs.legal_moves
        engine.play_card(pid, move)
    scores = engine.final_scores
    assert scores is not None
    return scores


# ------------------------------------------------------------ basic contract


def test_is_player_controller() -> None:
    assert isinstance(SmartHeartsBot(), PlayerController)


def test_single_legal_move_returned_immediately() -> None:
    obs = make_obs(["2C", "KD"], ["2C"])
    assert SmartHeartsBot(seed=1).select_move(obs) == "2C"


def test_no_legal_moves_raises() -> None:
    obs = make_obs(["2C"], [])
    try:
        SmartHeartsBot().select_move(obs)
    except ValueError:
        return
    raise AssertionError("expected ValueError")


# --------------------------------------------------------------- heuristics


def test_duck_plays_highest_card_below_table_top() -> None:
    obs = make_obs(
        ["3C", "9C", "QC", "AC", "5D"],
        ["3C", "9C", "QC", "AC"],
        [("P3", "7C"), ("P1", "KC")],
    )
    assert rules_bot().select_move(obs) == "QC"


def test_duck_sloughs_queen_of_spades_under_higher_spade() -> None:
    obs = make_obs(["3S", "QS", "5C"], ["3S", "QS"], [("P3", "AS")])
    assert rules_bot().select_move(obs) == "QS"


def test_forced_win_avoids_queen_of_spades() -> None:
    obs = make_obs(["QS", "KS", "5C"], ["QS", "KS"], [("P3", "2S")])
    # Not last (trick has 1 of 4 cards): play low, but never the queen if avoidable.
    assert rules_bot().select_move(obs) == "KS"


def test_forced_win_as_last_player_sheds_highest() -> None:
    obs = make_obs(
        ["8D", "KD", "5C"],
        ["8D", "KD"],
        [("P1", "2D"), ("P2", "3D"), ("P3", "4D")],
    )
    assert rules_bot().select_move(obs) == "KD"


def test_void_dumps_queen_of_spades_first() -> None:
    obs = make_obs(["QS", "AH", "9D"], ["QS", "AH", "9D"], [("P3", "7C")], hearts_broken=True)
    assert rules_bot().select_move(obs) == "QS"


def test_void_dumps_highest_heart_without_queen() -> None:
    obs = make_obs(["2H", "KH", "9D"], ["2H", "KH", "9D"], [("P3", "7C")], hearts_broken=True)
    assert rules_bot().select_move(obs) == "KH"


def test_void_dumps_dangerous_high_spade_while_queen_is_out() -> None:
    obs = make_obs(["AS", "3H", "9D"], ["AS", "3H", "9D"], [("P3", "7C")], hearts_broken=True)
    assert rules_bot().select_move(obs) == "AS"


def test_lead_prefers_low_card_of_longest_plain_suit() -> None:
    hand = ["4C", "9C", "3D", "5D", "KD", "TD", "2S", "AH"]
    obs = make_obs(hand, hand, hearts_broken=True)
    assert rules_bot().select_move(obs) == "3D"


def test_lead_avoids_hearts_and_high_spades_when_alternatives_exist() -> None:
    hand = ["AS", "KS", "2H", "6C"]
    obs = make_obs(hand, hand, hearts_broken=True)
    assert rules_bot().select_move(obs) == "6C"


def test_lead_uses_low_spade_before_hearts() -> None:
    hand = ["4S", "AS", "2H"]
    obs = make_obs(hand, hand, hearts_broken=True)
    assert rules_bot().select_move(obs) == "4S"


def test_lead_with_only_dangerous_cards_plays_lowest_heart() -> None:
    hand = ["QS", "AS", "3H", "KH"]
    obs = make_obs(hand, hand, hearts_broken=True)
    assert rules_bot().select_move(obs) == "3H"


# ------------------------------------------------------- hidden-state model


def _midgame_observation(seed: int, plays: int) -> tuple[HeartsGameEngine, PlayerObservation]:
    engine = HeartsGameEngine(4, seed=seed)
    rng = random.Random(seed)
    for _ in range(plays):
        pid = engine.current_player
        assert pid is not None
        engine.play_card(pid, rng.choice(engine.get_legal_moves(pid)))
    pid = engine.current_player
    assert pid is not None
    return engine, engine.get_player_observation(pid)


def test_context_unknown_cards_exclude_hand_and_played() -> None:
    _, obs = _midgame_observation(seed=3, plays=23)
    ctx = _build_context(obs)
    assert ctx is not None
    played = {Card.parse(c) for _, c in obs.current_trick}
    assert not set(ctx.unknown) & set(ctx.hand)
    assert not set(ctx.unknown) & played
    assert len(ctx.unknown) == sum(ctx.capacities.values())
    assert len(ctx.unknown) + len(ctx.hand) + 23 == 52


def test_sampled_worlds_match_hand_sizes_and_voids() -> None:
    for seed in range(10):
        engine, obs = _midgame_observation(seed=seed, plays=30)
        ctx = _build_context(obs)
        assert ctx is not None
        rng = random.Random(seed)
        for _ in range(5):
            world = _deal_unknown(ctx.unknown, ctx.capacities, ctx.voids, rng)
            dealt = [c for cards in world.values() for c in cards]
            assert sorted(dealt) == sorted(ctx.unknown)
            for pid, cards in world.items():
                assert len(cards) == ctx.capacities[pid]
                assert not any(c.suit in ctx.voids[pid] for c in cards)
                # The real hidden hand is one of the possible worlds' constraints.
                real = [Card.parse(c) for c in engine.get_player_observation(pid).hand]
                assert not any(c.suit in ctx.voids[pid] for c in real)


def test_inconsistent_observation_falls_back_to_heuristics() -> None:
    obs = make_obs(["3C", "QC", "AC"], ["3C", "QC", "AC"], [("P3", "7C"), ("P1", "KC")])
    assert _build_context(obs) is None
    assert SmartHeartsBot(seed=1).select_move(obs) == "QC"


# --------------------------------------------------------------- full games


def test_smart_bots_play_full_legal_deal() -> None:
    engine = HeartsGameEngine(4, seed=11)
    bots = {pid: SmartHeartsBot(num_samples=6, seed=i) for i, pid in enumerate(engine.player_ids)}
    scores = play_deal(engine, bots)
    assert sum(scores.values()) in {26, 78}


def test_other_player_counts_work() -> None:
    for n in (2, 3, 5):
        engine = HeartsGameEngine(n, seed=n)
        bots = {pid: SmartHeartsBot(num_samples=3, seed=i) for i, pid in enumerate(engine.player_ids)}
        scores = play_deal(engine, bots)
        assert set(scores) == set(engine.player_ids)


def test_same_seed_gives_same_decision() -> None:
    _, obs = _midgame_observation(seed=5, plays=20)
    a = SmartHeartsBot(num_samples=10, seed=42).select_move(obs)
    b = SmartHeartsBot(num_samples=10, seed=42).select_move(obs)
    assert a == b
    assert a in obs.legal_moves


def test_smart_bot_beats_random_players() -> None:
    smart_total = 0
    random_total = 0
    deals = 12
    for seed in range(deals):
        engine = HeartsGameEngine(4, seed=seed)
        rng = random.Random(seed)
        controllers: dict[str, PlayerController] = {
            pid: RandomBot(rng) for pid in engine.player_ids
        }
        controllers["P0"] = SmartHeartsBot(num_samples=8, seed=seed)
        scores = play_deal(engine, controllers)
        smart_total += scores["P0"]
        random_total += sum(v for p, v in scores.items() if p != "P0") / 3
    assert smart_total / deals < random_total / deals