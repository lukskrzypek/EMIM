"""Move evaluator ported from the "kierki" scoring library, adapted to the King engine."""

from __future__ import annotations

import random

import pytest

from engine.contracts import CONTRACT_ORDER, GameContract
from engine.state import GameState as Engine
from evaluation import GameState, InvalidState, evaluate_all, evaluate_move
from evaluation.cards import full_deck, total_tricks
from evaluation.report import build_report
from evaluation.trajectories import LoadResult, LoggedMove


def test_decks_match_engine_for_every_player_count() -> None:
    for players in (3, 4):
        engine = Engine.new(players, seed=0)
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
        contract=GameContract.NO_HEARTS,
        current_trick=["3c", "5c"],
    )
    scores = {e.card: (e.correctness, e.aggressiveness, e.scenario) for e in evaluate_all(state)}
    assert scores == {
        "Kc": (99.4, 42.0, "follow_take"),
        "2c": (64.5, 15.0, "follow_duck"),
    }


def _queens_state(**overrides: object) -> GameState:
    base: dict[str, object] = {
        "hand": ["3S", "KS", "2H", "5C", "6C", "7C", "8C", "9C", "TD", "JD", "QD", "KD", "AD"],
        "contract": GameContract.NO_QUEENS,
        "current_trick": ["2S", "QS"],
        "legal_moves": ["3S", "KS"],
    }
    base.update(overrides)
    return GameState(**base)  # type: ignore[arg-type]


def test_queens_ducking_under_the_queen_beats_taking_it() -> None:
    duck = evaluate_move(_queens_state(), "3S")
    take = evaluate_move(_queens_state(), "KS")
    assert duck.legal and take.legal
    assert duck.correctness == 100.0
    assert take.correctness is not None and take.correctness < 40
    assert (take.aggressiveness or 0) > (duck.aggressiveness or 100)


def test_engine_legal_moves_override_follow_suit_rule() -> None:
    # Spades are led and the hand holds spades, so only 3S/KS are legal.
    result = evaluate_move(_queens_state(), "5C")
    assert not result.legal
    assert result.errors

    # Without the engine's list the follow-suit rule still rejects it.
    assert not evaluate_move(_queens_state(legal_moves=None), "5C").legal


def test_legal_moves_outside_the_hand_are_rejected() -> None:
    with pytest.raises(InvalidState):
        evaluate_move(_queens_state(legal_moves=["3S", "AS"]), "3S")


def test_single_legal_card_is_a_forced_move() -> None:
    result = evaluate_move(_queens_state(legal_moves=["3S"]), "3S")
    assert result.scenario == "only_move"
    assert result.correctness == 100.0
    assert result.aggressiveness is None


def test_three_player_deck_has_no_two_of_clubs() -> None:
    hand = [f"{r}H" for r in "23456789TJQKA"] + ["3C", "4C", "5C", "6C"]
    state = GameState(hand, GameContract.NO_QUEENS, num_players=3)
    assert len(hand) == total_tricks(3) == 17
    assert evaluate_move(state, "3C").legal
    bad = GameState([*hand[:-1], "2C"], GameContract.NO_QUEENS, num_players=3)
    with pytest.raises(InvalidState, match="spoza talii"):
        evaluate_move(bad, "2C")


def test_hand_size_must_match_tricks_played() -> None:
    with pytest.raises(InvalidState):
        evaluate_move(GameState(["2C"], GameContract.NO_QUEENS), "2C")


def test_unsupported_player_count_is_rejected() -> None:
    hand = [str(c) for c in full_deck(4)][:26]
    with pytest.raises(ValueError):
        evaluate_move(GameState(hand, GameContract.NO_HEARTS, num_players=2), hand[0])


@pytest.mark.parametrize("players", [3, 4])
def test_scores_stay_in_range_for_random_play_in_every_contract(players: int) -> None:
    """Evaluate every legal move of random deals: no crashes, scores within 0-100."""
    rng = random.Random(3)
    for index, contract in enumerate(CONTRACT_ORDER):
        engine = Engine.new(players, seed=players, start_deal=index + 1)
        engine.auto_advance = False
        assert engine.current_contract is contract
        plays: list[str] = []
        while not engine.deal_finished:
            pid = engine.current_player
            assert pid is not None
            obs = engine.get_player_observation(pid)
            done = (obs.trick_number - 1) * players
            state = GameState(
                hand=obs.hand,
                contract=obs.contract,
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

# ---------------------------------------------------------------------------
# Dorzucanie kar: pułapka pod wysoką kartą i znany renons.
# Miejsca w historii liczone są od gracza wychodzącego w 1. lewie (miejsce 0);
# kolejną lewę otwiera zwycięzca poprzedniej.

def _score(state: GameState, card: str) -> float:
    result = evaluate_move(state, card)
    assert result.legal and result.correctness is not None, result.errors
    return result.correctness


_CLEAN_HAND = ["KS", "AS", "3S", "4S", "5C", "6C", "7C", "8C", "9C", "2D", "3D", "4D", "5D"]


@pytest.mark.parametrize("card", ["KS", "AS"])
def test_leading_above_an_unseen_queen_is_almost_never_correct(card: str) -> None:
    # Bez dam, nie mam QS, QS nie wyszła: każdy przeciwnik dorzuci mi ją pod króla/asa.
    state = GameState(_CLEAN_HAND, GameContract.NO_QUEENS)
    assert _score(state, card) <= 10
    assert _score(state, "3S") >= 90


def test_leading_a_king_after_the_queen_is_gone_is_fine() -> None:
    # Lewa 1: 2S, QS, 5S, 9S -> bierze miejsce 3 (ja) i wychodzę w lewie 2.
    hand = ["KS", "4S", "5C", "6C", "7C", "8C", "9C", "2D", "3D", "4D", "5D", "6D"]
    state = GameState(hand, GameContract.NO_QUEENS, history=[["2S", "QS", "5S", "9S"]])
    assert _score(state, "KS") >= 70


def test_leading_above_unseen_men_in_no_men_is_almost_never_correct() -> None:
    hand = ["AS", "2S", "3S", "4C", "5C", "6C", "7C", "8C", "9C", "2D", "3D", "4D", "5D"]
    state = GameState(hand, GameContract.NO_MEN)
    assert _score(state, "AS") <= 10      # KS i JS spadną mi pod asa
    assert _score(state, "2S") >= 90


@pytest.mark.parametrize(("trick", "limit"), [(["2S"], 25), (["2S", "7S"], 50)])
def test_following_high_over_an_unseen_queen_is_bad(trick: list[str], limit: float) -> None:
    # Im więcej graczy po mnie, tym pewniej dostanę damę.
    state = GameState(_CLEAN_HAND, GameContract.NO_QUEENS, current_trick=trick)
    assert _score(state, "KS") <= limit
    assert _score(state, "KS") < _score(state, "3S")


def _declined_queen_state(next_declined: bool) -> GameState:
    """Bez dam, lewa 3: miejsce 1 wyszło 8S, miejsce 2 dołożyło 9S, gram ja (miejsce 3) i po mnie
    zostaje tylko miejsce 0. W lewie 2 król pików bierze lewę; ``next_declined``: miejsce 0 dołożyło
    niskiego pika już PO królu (mogło bezpiecznie dorzucić damę, a nie dorzuciło), inaczej zagrało
    przed królem i niczego nie zdradziło."""
    if next_declined:
        trick1 = ["2C", "AC", "3C", "4C"]   # miejsca 0, 1, 2, 3 (ja) -> bierze miejsce 1
        trick2 = ["KS", "6S", "5S", "7S"]   # miejsca 1, 2, 3 (ja), 0 -> bierze miejsce 1
    else:
        trick1 = ["2C", "3C", "4C", "AC"]   # miejsca 0, 1, 2, 3 (ja) -> biorę
        trick2 = ["7S", "6S", "KS", "5S"]   # miejsca 3 (ja), 0, 1, 2 -> bierze miejsce 1
    hand = ["AS", "3S", "4S", "5D", "6D", "7D", "8D", "9D", "TD", "JD", "2H"]
    return GameState(hand, GameContract.NO_QUEENS, history=[trick1, trick2],
                     current_trick=["8S", "9S"])


def test_next_player_who_did_not_drop_the_queen_under_a_king_probably_has_none() -> None:
    informed = _score(_declined_queen_state(next_declined=True), "AS")
    blind = _score(_declined_queen_state(next_declined=False), "AS")
    assert informed > blind + 15
    assert 70 <= informed < 90      # poprawne, ale mógł blefować - nie optymalne


def _void_state(contract: GameContract, spades: list[str]) -> GameState:
    """Lewa 4, wychodzę ja (miejsce 3). W lewie 1 miejsce 1 nie dołożyło do pików - ma renons
    i zagra po mnie. Wyżej od mojego JS nie ma już pików, więc JS bierze lewę."""
    history = [
        ["KS", "3D", "QS", "AS"],   # miejsca 0, 1 (renons pik), 2, 3 (ja) -> biorę
        ["2C", "3C", "4C", "AC"],   # ja, 0, 1, 2 -> bierze miejsce 2
        ["5C", "KC", "6C", "7C"],   # miejsca 2, 3 (ja), 0, 1 -> biorę
    ]
    others = ["4D", "5D", "6D", "7D", "8D", "9D", "8C", "9C", "2H"]
    hand = spades + others[: 10 - len(spades)]
    return GameState(hand, contract, history=history)


def test_leading_into_a_known_void_in_no_queens_is_a_nightmare() -> None:
    state = _void_state(GameContract.NO_QUEENS, ["JS", "4S", "5S"])
    assert _score(state, "JS") <= 25
    assert _score(state, "4D") >= 70
    # Nawet pozbywając się koloru (ostatnie piki) dama to zbyt wysoka cena.
    assert _score(_void_state(GameContract.NO_QUEENS, ["JS", "4S"]), "JS") <= 25


def test_leading_into_a_known_void_in_no_hearts() -> None:
    long_suit = _void_state(GameContract.NO_HEARTS, ["JS", "4S", "5S"])
    assert _score(long_suit, "JS") < 70
    # Przedostatni pik: pozbywam się koloru płacąc kierem - akceptowalne.
    shed = _void_state(GameContract.NO_HEARTS, ["JS", "4S"])
    assert _score(shed, "JS") >= 70
    assert _score(shed, "JS") > _score(long_suit, "JS")


def test_void_dump_hurts_more_where_penalties_are_higher() -> None:
    spades = ["JS", "4S", "5S"]
    queens = _score(_void_state(GameContract.NO_QUEENS, spades), "JS")
    king = _score(_void_state(GameContract.NO_KING_OF_HEARTS, spades), "JS")
    hearts = _score(_void_state(GameContract.NO_HEARTS, spades), "JS")
    assert king <= queens < hearts


def test_lowest_card_of_a_suit_someone_lacks_is_a_very_good_lead() -> None:
    # 2S jest najniższym pikiem w grze: ktoś z pikami musi dołożyć wyżej i to on dostanie
    # zrzuconą damę od gracza z renonsem. 5S nie jest najniższy (3S i 4S są u przeciwników).
    state = _void_state(GameContract.NO_QUEENS, ["JS", "2S", "5S"])
    assert _score(state, "2S") >= 90
    assert _score(state, "5S") < _score(state, "2S")
    assert _score(state, "2S") > _score(state, "JS") + 50


def test_lowest_card_lead_without_a_known_void_follows_the_usual_rules() -> None:
    # Ta sama ręka, ale nikt nie pokazał renonsu: długi kolor bez kar - nic nie daje.
    history = [["KS", "3S", "QS", "AS"], ["2C", "3C", "4C", "AC"], ["5C", "KC", "6C", "7C"]]
    hand = ["JS", "2S", "5S", "4D", "5D", "6D", "7D", "8D", "9D", "8C"]
    state = GameState(hand, GameContract.NO_QUEENS, history=history)
    assert _score(state, "2S") < 90


@pytest.mark.parametrize("card", ["AS", "5S", "5C", "TD"])
def test_every_move_is_optimal_when_no_penalty_is_left(card: str) -> None:
    # Wszystkie damy już zagrane - nie ma czego zepsuć.
    history = [["QS", "2S", "3S", "4S"], ["QH", "2H", "3H", "4H"],
               ["QD", "2D", "3D", "4D"], ["QC", "2C", "3C", "4C"]]
    hand = ["AS", "5S", "6S", "5C", "6C", "7C", "8D", "9D", "TD"]
    result = evaluate_move(GameState(hand, GameContract.NO_QUEENS, history=history), card)
    assert result.scenario == "nothing_left"
    assert result.correctness == 100.0


def test_king_of_hearts_contract_is_over_once_the_king_falls() -> None:
    history = [["KH", "2H", "3H", "4H"]]
    hand = ["AH", "5H", "6S", "7S", "8S", "5C", "6C", "7C", "8D", "9D", "TD", "JD"]
    results = evaluate_all(GameState(hand, GameContract.NO_KING_OF_HEARTS, history=history))
    assert {e.scenario for e in results} == {"nothing_left"}


def test_trick_penalties_keep_moves_meaningful() -> None:
    # W "bez lew" każda lewa jest karana - nigdy nie ma "nic do stracenia".
    state = GameState(_CLEAN_HAND, GameContract.NO_TRICKS)
    assert all(e.scenario != "nothing_left" for e in evaluate_all(state))


def _duck_state(late: bool) -> GameState:
    """Na stole 9S i JS, mam TS i 2S (oba nie biorą lewy), wyższych pików nie mam."""
    current = ["9S", "JS"]
    if not late:
        hand = ["TS", "2S", "3C", "4C", "5C", "6C", "7C", "8C", "2D", "3D", "4D", "5D", "6D"]
        return GameState(hand, GameContract.NO_HEARTS, current_trick=current)
    hand = ["TS", "2S", "5D"]
    used = set(hand + current)
    rest = [str(c).upper().replace("10", "T") for c in full_deck(4)]
    # w grze zostają 3S-8S (między 2S a TS są niewidziane piki, więc karty nie są równoważne)
    # i AH (jest jeszcze o co grać)
    used |= {"3S", "4S", "5S", "6S", "7S", "8S", "AH"}
    rest = [c for c in rest if c not in used]
    history = [rest[i:i + 4] for i in range(0, 40, 4)]
    return GameState(hand, GameContract.NO_HEARTS, history=history, current_trick=current)


@pytest.mark.parametrize("late", [False, True])
def test_ducking_with_a_low_card_while_holding_a_higher_safe_one_is_punished(late: bool) -> None:
    state = _duck_state(late)
    assert _score(state, "TS") >= 90
    assert _score(state, "2S") <= 35


def test_wasting_a_low_card_under_a_higher_one_is_worse_late_in_the_deal() -> None:
    assert _score(_duck_state(late=True), "2S") < _score(_duck_state(late=False), "2S")


def test_moves_with_nothing_left_to_take_are_left_out_of_the_statistics() -> None:
    history = [["QS", "2S", "3S", "4S"], ["QH", "2H", "3H", "4H"],
               ["QD", "2D", "3D", "4D"], ["QC", "2C", "3C", "4C"]]
    hand = ["AS", "5S", "6S", "5C", "6C", "7C", "8D", "9D", "TD"]
    nothing = GameState(hand, GameContract.NO_QUEENS, history=history)
    real = GameState(_CLEAN_HAND, GameContract.NO_QUEENS)
    load = LoadResult(moves=[LoggedMove(1, "P0", "bot", "AS", nothing),
                             LoggedMove(2, "P0", "bot", "KS", real)], records=2)
    stats = build_report(load).models["bot"]
    assert stats.moves == 2 and stats.forced == 1 and stats.decisions == 1
    assert stats.correctness == evaluate_move(real, "KS").correctness


_KQ_HAND = ["TS", "9S", "2S", "3C", "4C", "5C", "6C", "7C", "8C", "2D", "3D", "4D", "5D"]


def test_ducking_two_under_king_and_queen_while_holding_ten_is_very_wrong() -> None:
    state = GameState(_KQ_HAND, GameContract.NO_HEARTS, current_trick=["KS", "QS"])
    assert _score(state, "TS") == 100.0
    assert _score(state, "2S") <= 35


def test_adjacent_cards_of_a_suit_are_equivalent() -> None:
    # Między 9S a TS nie ma żadnej niewidzianej karty - zrzucenie 9S niczego nie traci.
    state = GameState(_KQ_HAND, GameContract.NO_HEARTS, current_trick=["KS", "QS"])
    assert _score(state, "9S") == _score(state, "TS")


def test_discarding_within_a_suit_keeps_the_higher_card_rule() -> None:
    # Brak trefli, zrzucam piki: TS zamiast QS to zły ruch (w "bez lew" karty nie są punktowane).
    hand = ["QS", "TS", "4S", "AD", "KD", "QD", "JD", "9D", "8D", "7D", "6D", "5D", "4D"]
    state = GameState(hand, GameContract.NO_TRICKS, current_trick=["2C"])
    assert _score(state, "QS") >= 90
    assert _score(state, "TS") < 70
    assert _score(state, "4S") < _score(state, "TS")


def test_last_card_of_a_suit_may_be_discarded_before_a_high_card_of_a_long_suit() -> None:
    # Ostatni pik (5S) zamiast asa karo przy długich karach - kolor wybieram swobodnie.
    hand = ["5S", "AD", "KD", "TD", "9D", "8D", "7D", "6D", "5D", "4D", "3D", "2D", "4H"]
    state = GameState(hand, GameContract.NO_TRICKS, current_trick=["2C"])
    assert _score(state, "5S") >= _score(state, "AD") >= 85
    assert _score(state, "2D") < 70


def test_penalty_card_is_discarded_before_a_higher_card_of_the_same_suit() -> None:
    # Bez dam, brak trefli: najpierw dama, choć as jest wyższy.
    hand = ["AS", "QS", "4S", "AD", "KD", "TD", "9D", "8D", "7D", "6D", "5D", "4D", "3H"]
    state = GameState(hand, GameContract.NO_QUEENS, current_trick=["2C"])
    assert _score(state, "QS") >= 95
    assert _score(state, "AS") < 40
