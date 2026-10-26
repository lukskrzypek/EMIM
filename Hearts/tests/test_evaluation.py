"""Move evaluator ported from the "kierki" scoring library, adapted to the Hearts engine."""

from __future__ import annotations

import random

import pytest

from engine.game import HeartsGameEngine
from evaluation import GameState, InvalidState, RoundType, evaluate_all, evaluate_move
from evaluation.cards import full_deck, total_tricks


def test_decks_match_engine_for_every_player_count() -> None:
    for players in (2, 3, 4, 5):
        engine = HeartsGameEngine(players, seed=0)
        dealt = sum(len(engine.get_player_observation(p).hand) for p in engine.player_ids)
        assert len(full_deck(players)) == dealt
        assert total_tricks(players) == dealt // players


def test_full_deck_rejects_unsupported_player_count() -> None:
    with pytest.raises(ValueError):
        full_deck(6)


def test_port_keeps_original_four_player_scores() -> None:
    """Values produced by the original ``kierki`` package for this position."""
    state = GameState(
        hand=["9h", "4h", "2c", "Kc", "As", "3d", "5d", "7d", "8d", "9d", "Jd", "Qs", "2s"],
        round_type=RoundType.NO_HEARTS,
        current_trick=["3c", "5c"],
    )
    scores = {e.card: (e.correctness, e.aggressiveness, e.scenario) for e in evaluate_all(state)}
    assert scores == {
        "Kc": (99.4, 42.0, "follow_take"),
        "2c": (64.5, 15.0, "follow_duck"),
    }


def _hearts_state(**overrides: object) -> GameState:
    base: dict[str, object] = {
        "hand": ["3S", "KS", "2H", "5C", "6C", "7C", "8C", "9C", "TD", "JD", "QD", "KD", "AD"],
        "round_type": RoundType.HEARTS,
        "current_trick": ["2S", "QS"],
        "legal_moves": ["3S", "KS"],
    }
    base.update(overrides)
    return GameState(**base)  # type: ignore[arg-type]


def test_hearts_ducking_under_the_queen_beats_taking_it() -> None:
    duck = evaluate_move(_hearts_state(), "3S")
    take = evaluate_move(_hearts_state(), "KS")
    assert duck.legal and take.legal
    assert duck.correctness == 100.0
    assert take.correctness is not None and take.correctness < 40
    assert (take.aggressiveness or 0) > (duck.aggressiveness or 100)


def test_engine_legal_moves_override_follow_suit_rule() -> None:
    # Spades are led and the hand holds spades, so only 3S/KS are legal.
    result = evaluate_move(_hearts_state(), "5C")
    assert not result.legal
    assert result.errors

    # Without the engine's list the follow-suit rule still rejects it.
    assert not evaluate_move(_hearts_state(legal_moves=None), "5C").legal


def test_legal_moves_outside_the_hand_are_rejected() -> None:
    with pytest.raises(InvalidState):
        evaluate_move(_hearts_state(legal_moves=["3S", "AS"]), "3S")


def test_single_legal_card_is_a_forced_move() -> None:
    result = evaluate_move(_hearts_state(legal_moves=["3S"]), "3S")
    assert result.scenario == "only_move"
    assert result.correctness == 100.0
    assert result.aggressiveness is None


def test_three_player_deck_has_no_two_of_diamonds() -> None:
    hand = [f"{r}H" for r in "23456789TJQKA"] + ["2C", "3C", "4C", "5C"]
    state = GameState(hand, RoundType.HEARTS, num_players=3)
    assert len(hand) == total_tricks(3) == 17
    assert evaluate_move(state, "2C").legal
    bad = GameState([*hand[:-1], "2D"], RoundType.HEARTS, num_players=3)
    with pytest.raises(InvalidState, match="spoza talii"):
        evaluate_move(bad, "2D")


def test_hand_size_must_match_tricks_played() -> None:
    with pytest.raises(InvalidState):
        evaluate_move(GameState(["2C"], RoundType.HEARTS), "2C")


def test_kierki_rounds_other_than_hearts_need_four_players() -> None:
    hand = [str(c) for c in full_deck(2)][:26]
    with pytest.raises(InvalidState):
        evaluate_move(GameState(hand, RoundType.NO_HEARTS, num_players=2), hand[0])


def test_scores_stay_in_range_for_random_play_at_every_table_size() -> None:
    """Evaluate every legal move of random deals: no crashes, scores within 0-100."""
    rng = random.Random(3)
    for players in (2, 3, 4, 5):
        engine = HeartsGameEngine(players, seed=players)
        plays: list[str] = []
        while not engine.is_over:
            pid = engine.current_player
            assert pid is not None
            obs = engine.get_player_observation(pid)
            done = (obs.trick_number - 1) * players
            state = GameState(
                hand=obs.hand,
                round_type=RoundType.HEARTS,
                history=[plays[i:i + players] for i in range(0, done, players)],
                current_trick=[c for _, c in obs.current_trick],
                num_players=players,
                legal_moves=obs.legal_moves,
            )
            results = evaluate_all(state)
            assert {e.card.upper().replace("10", "T") for e in results} == set(obs.legal_moves)
            for e in results:
                assert e.legal and e.correctness is not None
                assert 0.0 <= e.correctness <= 100.0
                assert e.aggressiveness is None or 0.0 <= e.aggressiveness <= 100.0
            move = rng.choice(obs.legal_moves)
            plays.append(move)
            engine.play_card(pid, move)
