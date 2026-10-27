"""Tests for SmartHeartsBot: heuristics, hidden-hand inference, Monte Carlo play."""

from __future__ import annotations

import random

import pytest

from controllers.base import PlayerController
from controllers.smart_bot import SmartHeartsBot, _build_context, _deal_unknown
from engine.contracts import CONTRACT_ORDER, GameContract, contract_total_penalty
from engine.models import Card
from engine.observation import PlayerObservation
from engine.state import GameState


def make_obs(
    hand: list[str],
    legal: list[str],
    trick: list[tuple[str, str]] | None = None,
    *,
    contract: GameContract = GameContract.NO_TRICKS,
    trick_number: int = 5,
) -> PlayerObservation:
    return PlayerObservation(
        player_id="P0",
        hand=hand,
        current_trick=trick or [],
        trick_history=[],
        exposed_voids={},
        scores={"P0": 0, "P1": 0, "P2": 0, "P3": 0},
        legal_moves=legal,
        trick_number=trick_number,
        current_player="P0",
        contract=contract,
    )


def rules_bot() -> SmartHeartsBot:
    """Heuristics only (no simulation)."""
    return SmartHeartsBot(num_samples=0)


class RandomBot(PlayerController):
    def __init__(self, rng: random.Random) -> None:
        self._rng = rng

    def select_move(self, observation: PlayerObservation) -> str:
        return self._rng.choice(observation.legal_moves)


def play_deal(state: GameState, controllers: dict[str, PlayerController]) -> dict[str, int]:
    """Play the current deal to its end (the state must not auto-advance)."""
    state.auto_advance = False
    while not (state.deal_finished or state.is_over):
        pid = state.current_player
        assert pid is not None
        obs = state.get_player_observation(pid)
        move = controllers[pid].select_move(obs)
        assert move in obs.legal_moves
        state.play_card(pid, move)
    return dict(state.scores)


# ------------------------------------------------------------ basic contract


def test_is_player_controller() -> None:
    assert isinstance(SmartHeartsBot(), PlayerController)


def test_single_legal_move_returned_immediately() -> None:
    obs = make_obs(["2C", "KD"], ["2C"])
    assert SmartHeartsBot(seed=1).select_move(obs) == "2C"


def test_no_legal_moves_raises() -> None:
    with pytest.raises(ValueError):
        SmartHeartsBot().select_move(make_obs(["2C"], []))


# --------------------------------------------------------------- heuristics


def test_duck_plays_highest_card_below_table_top() -> None:
    obs = make_obs(["3C", "9C", "QC", "AC", "5D"], ["3C", "9C", "QC", "AC"], [("P3", "7C"), ("P1", "KC")])
    assert rules_bot().select_move(obs) == "QC"


def test_duck_sloughs_queen_under_higher_card() -> None:
    obs = make_obs(
        ["3S", "QS", "5C"], ["3S", "QS"], [("P3", "AS")], contract=GameContract.NO_QUEENS
    )
    assert rules_bot().select_move(obs) == "QS"


def test_forced_win_avoids_penalty_card() -> None:
    obs = make_obs(
        ["QS", "KS", "5C"], ["QS", "KS"], [("P3", "2S")], contract=GameContract.NO_QUEENS
    )
    # Not last (1 of 4 cards on the table): play the harmless card.
    assert rules_bot().select_move(obs) == "KS"


def test_forced_win_as_last_player_sheds_highest() -> None:
    obs = make_obs(
        ["8D", "KD", "5C"], ["8D", "KD"], [("P1", "2D"), ("P2", "3D"), ("P3", "4D")]
    )
    assert rules_bot().select_move(obs) == "KD"


@pytest.mark.parametrize(
    ("contract", "hand", "expected"),
    [
        (GameContract.NO_QUEENS, ["QS", "AH", "9D"], "QS"),
        (GameContract.NO_HEARTS, ["2H", "KH", "QS"], "KH"),
        (GameContract.NO_MEN, ["QS", "JD", "AH"], "JD"),
        (GameContract.NO_KING_OF_HEARTS, ["KH", "AS", "9D"], "KH"),
        (GameContract.NO_TRICKS, ["2S", "AS", "9D"], "AS"),
    ],
)
def test_void_dumps_the_costliest_card(
    contract: GameContract, hand: list[str], expected: str
) -> None:
    obs = make_obs(hand, hand, [("P3", "7C")], contract=contract)
    assert rules_bot().select_move(obs) == expected


def test_lead_prefers_lowest_card_and_longer_suit_on_ties() -> None:
    hand = ["3C", "3D", "5D", "KD"]
    obs = make_obs(hand, hand)
    assert rules_bot().select_move(obs) == "3D"


def test_lead_avoids_penalty_cards_when_alternatives_exist() -> None:
    hand = ["2H", "AS", "6C"]
    obs = make_obs(hand, hand, contract=GameContract.NO_HEARTS)
    assert rules_bot().select_move(obs) == "6C"


def test_lead_with_only_penalty_cards_plays_lowest() -> None:
    hand = ["3H", "KH"]
    obs = make_obs(hand, hand, contract=GameContract.NO_HEARTS)
    assert rules_bot().select_move(obs) == "3H"


# ------------------------------------------------------- hidden-state model


def _midgame_observation(seed: int, plays: int, players: int = 4) -> tuple[GameState, PlayerObservation]:
    state = GameState.new(players, seed=seed)
    state.auto_advance = False
    rng = random.Random(seed)
    for _ in range(plays):
        pid = state.current_player
        assert pid is not None
        state.play_card(pid, rng.choice(state.get_legal_moves(pid)))
    pid = state.current_player
    assert pid is not None
    return state, state.get_player_observation(pid)


def test_context_unknown_cards_exclude_hand_and_played() -> None:
    _, obs = _midgame_observation(seed=3, plays=23)
    ctx = _build_context(obs)
    assert ctx is not None
    played = {Card.parse(c) for _, c in obs.played_cards}
    assert not set(ctx.unknown) & set(ctx.hand)
    assert not set(ctx.unknown) & played
    assert len(ctx.unknown) == sum(ctx.capacities.values())
    assert len(ctx.unknown) + len(ctx.hand) + 23 == 52


def test_context_for_three_players_uses_51_card_deck() -> None:
    _, obs = _midgame_observation(seed=2, plays=10, players=3)
    ctx = _build_context(obs)
    assert ctx is not None
    assert Card.parse("2C") not in ctx.unknown
    assert len(ctx.unknown) + len(ctx.hand) + 10 == 51


def test_sampled_worlds_match_hand_sizes_and_voids() -> None:
    for seed in range(10):
        state, obs = _midgame_observation(seed=seed, plays=30)
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
                # The real hidden hand respects the exposed voids too.
                real = [Card.parse(c) for c in state.get_player_observation(pid).hand]
                assert not any(c.suit in ctx.voids[pid] for c in real)


def test_inconsistent_observation_falls_back_to_heuristics() -> None:
    obs = make_obs(["3C", "QC", "AC"], ["3C", "QC", "AC"], [("P3", "7C"), ("P1", "KC")])
    assert _build_context(obs) is None
    assert SmartHeartsBot(seed=1).select_move(obs) == "QC"


# --------------------------------------------------------------- full games


@pytest.mark.parametrize("contract", list(GameContract))
def test_smart_bots_play_full_legal_deal_in_every_contract(contract: GameContract) -> None:
    start_deal = CONTRACT_ORDER.index(contract) + 1
    state = GameState.new(4, seed=11, start_deal=start_deal)
    bots = {pid: SmartHeartsBot(num_samples=2, seed=i) for i, pid in enumerate(state.player_ids)}
    scores = play_deal(state, bots)
    assert state.current_contract is contract
    assert sum(scores.values()) == contract_total_penalty(contract, 4)


@pytest.mark.parametrize("players", [3, 4])
def test_rule_bots_play_a_whole_match(players: int) -> None:
    state = GameState.new(players, seed=7)
    bots = {pid: SmartHeartsBot(num_samples=0) for pid in state.player_ids}
    while not state.is_over:
        play_deal(state, bots)
        if not state.is_over:
            state.start_next_deal()
    expected = sum(contract_total_penalty(c, players) for c in CONTRACT_ORDER)
    assert sum(state.total_scores.values()) == expected


def test_same_seed_gives_same_decision() -> None:
    _, obs = _midgame_observation(seed=5, plays=20)
    a = SmartHeartsBot(num_samples=10, seed=42).select_move(obs)
    b = SmartHeartsBot(num_samples=10, seed=42).select_move(obs)
    assert a == b
    assert a in obs.legal_moves


def test_smart_bot_beats_random_players() -> None:
    smart_total = 0.0
    random_total = 0.0
    deals = 0
    for contract in CONTRACT_ORDER:
        for seed in range(2):
            state = GameState.new(4, seed=seed, start_deal=CONTRACT_ORDER.index(contract) + 1)
            rng = random.Random(seed)
            controllers: dict[str, PlayerController] = {
                pid: RandomBot(rng) for pid in state.player_ids
            }
            controllers["P0"] = SmartHeartsBot(num_samples=6, seed=seed)
            scores = play_deal(state, controllers)
            smart_total += scores["P0"]
            random_total += sum(v for p, v in scores.items() if p != "P0") / 3
            deals += 1
    assert smart_total / deals < random_total / deals
