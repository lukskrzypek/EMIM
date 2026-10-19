"""GroqICLBot tests: the Groq API is mocked, no key or network needed."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from controllers.base import PlayerController
from controllers.groq_icl_bot import DEFAULT_MODEL, GroqICLBot, parse_card, read_api_key
from engine.game import PlayerObservation


class FakeClient:
    """Mimics ``groq.Groq``: ``client.chat.completions.create(...)``."""

    def __init__(self, reply: str = "", error: Exception | None = None) -> None:
        self.calls: list[dict[str, Any]] = []
        self._reply = reply
        self._error = error
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        if self._error is not None:
            raise self._error
        message = self._reply if not isinstance(self._reply, str) else SimpleNamespace(content=self._reply)
        return SimpleNamespace(choices=[SimpleNamespace(message=message)])


def make_obs(legal: list[str], player_id: str = "P1") -> PlayerObservation:
    return PlayerObservation(
        player_id=player_id,
        hand=["3C", "QC", "AC", "QS"],
        current_trick=[("P0", "KC")],
        trick_history=[],
        exposed_voids={"P0": [], "P1": []},
        hearts_broken=False,
        scores={"P0": 0, "P1": 0},
        legal_moves=legal,
        trick_number=3,
        current_player=player_id,
        num_players=2,
    )


def write_trajectories(path: Path, n: int) -> None:
    with path.open("w", encoding="utf-8") as handle:
        for i in range(n):
            record = {
                "player_id": "P0",
                "prompt_context": f"HEARTS 2p | EXAMPLE-{i}",
                "legal_moves": ["3C", "9C"],
                "chosen_move": "9C",
                "reasoning": "",
            }
            handle.write(json.dumps(record) + "\n")
        # Forced move: carries no decision information, must be skipped.
        forced = {
            "player_id": "P0",
            "prompt_context": "FORCED-EXAMPLE",
            "legal_moves": ["2C"],
            "chosen_move": "2C",
            "reasoning": "",
        }
        handle.write(json.dumps(forced) + "\n")


@pytest.fixture(autouse=True)
def _no_project_exchange_log(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep unit tests from appending to logs/groq_exchanges.jsonl."""
    monkeypatch.setattr("controllers.groq_icl_bot.DEFAULT_EXCHANGE_LOG_PATH", None)


def test_is_player_controller() -> None:
    assert isinstance(GroqICLBot("P1", client=FakeClient()), PlayerController)


def test_default_model() -> None:
    assert GroqICLBot("P1", client=FakeClient()).model == DEFAULT_MODEL


def test_returns_card_from_json_reply() -> None:
    client = FakeClient('{"card": "QC"}')
    bot = GroqICLBot("P1", client=client)
    assert bot.select_move(make_obs(["3C", "QC", "AC"])) == "QC"
    assert len(client.calls) == 1
    assert client.calls[0]["model"] == DEFAULT_MODEL
    assert client.calls[0]["reasoning_effort"] == "low"


def test_single_legal_move_skips_api() -> None:
    client = FakeClient('{"card": "3C"}')
    assert GroqICLBot("P1", client=client).select_move(make_obs(["3C"])) == "3C"
    assert client.calls == []


def test_illegal_card_falls_back_to_first_legal() -> None:
    client = FakeClient('{"card": "AS"}')
    assert GroqICLBot("P1", client=client).select_move(make_obs(["3C", "QC"])) == "3C"


def test_empty_content_uses_json_card_from_reasoning() -> None:
    message = SimpleNamespace(content="", reasoning='Weighing 2C against QC.\n{"card": "QC"}')
    client = FakeClient()
    client._reply = message  # type: ignore[assignment]
    assert GroqICLBot("P1", client=client).select_move(make_obs(["3C", "QC"])) == "QC"


def test_api_reasoning_is_kept_for_the_log() -> None:
    message = SimpleNamespace(content='{"card": "QC"}', reasoning="Duck under the king.")
    client = FakeClient()
    client._reply = message  # type: ignore[assignment]
    bot = GroqICLBot("P1", client=client)
    assert bot.select_move(make_obs(["3C", "QC"])) == "QC"
    assert bot.last_reasoning == "Duck under the king."


def test_json_reasoning_is_kept_when_the_channel_is_empty() -> None:
    client = FakeClient('{"card": "QC", "reasoning": "safe duck"}')
    bot = GroqICLBot("P1", client=client)
    assert bot.select_move(make_obs(["3C", "QC"])) == "QC"
    assert bot.last_reasoning == "safe duck"


def test_exchange_log_stores_prompt_and_reply(tmp_path: Path) -> None:
    path = tmp_path / "groq_exchanges.jsonl"
    client = FakeClient('{"card": "QC", "reasoning": "safe duck"}')
    bot = GroqICLBot("P1", client=client, exchange_log_path=path)
    assert bot.select_move(make_obs(["3C", "QC"])) == "QC"

    record = json.loads(path.read_text(encoding="utf-8"))
    assert record["player_id"] == "P1"
    assert record["model"] == DEFAULT_MODEL
    assert [m["role"] for m in record["messages"]] == ["system", "user"]
    assert "Hearts" in record["messages"][0]["content"]
    assert "Legal" in record["messages"][1]["content"]
    assert record["response"] == {
        "content": '{"card": "QC", "reasoning": "safe duck"}',
        "reasoning": "",
    }
    assert record["chosen_move"] == "QC"
    assert record["error"] is None


def test_exchange_log_stores_api_errors(tmp_path: Path) -> None:
    path = tmp_path / "groq_exchanges.jsonl"
    client = FakeClient(error=RuntimeError("rate limited"))
    bot = GroqICLBot("P1", client=client, exchange_log_path=path)
    assert bot.select_move(make_obs(["3C", "QC"])) == "3C"
    record = json.loads(path.read_text(encoding="utf-8"))
    assert record["response"] is None
    assert record["error"] == "rate limited"
    assert record["messages"][1]["role"] == "user"


def test_single_legal_move_does_not_log_an_exchange(tmp_path: Path) -> None:
    path = tmp_path / "groq_exchanges.jsonl"
    bot = GroqICLBot("P1", client=FakeClient('{"card": "3C"}'), exchange_log_path=path)
    assert bot.select_move(make_obs(["3C"])) == "3C"
    assert not path.exists()


def test_single_legal_move_clears_previous_reasoning() -> None:
    bot = GroqICLBot("P1", client=FakeClient('{"card": "QC"}'))
    bot.last_reasoning = "stale"
    assert bot.select_move(make_obs(["3C"])) == "3C"
    assert bot.last_reasoning == ""


def test_reasoning_prose_without_json_is_not_a_move() -> None:
    message = SimpleNamespace(content="", reasoning="Maybe QC, but the table has 2C.")
    client = FakeClient()
    client._reply = message  # type: ignore[assignment]
    assert GroqICLBot("P1", client=client).select_move(make_obs(["3C", "QC"])) == "3C"


def test_unparsable_reply_falls_back_to_first_legal() -> None:
    client = FakeClient("I think I will pass.")
    assert GroqICLBot("P1", client=client).select_move(make_obs(["3C", "QC"])) == "3C"


def test_api_error_falls_back_to_first_legal() -> None:
    client = FakeClient(error=RuntimeError("rate limited"))
    assert GroqICLBot("P1", client=client).select_move(make_obs(["3C", "QC"])) == "3C"


def test_wrong_player_id_raises() -> None:
    bot = GroqICLBot("P0", client=FakeClient('{"card": "3C"}'))
    with pytest.raises(ValueError):
        bot.select_move(make_obs(["3C", "QC"], player_id="P1"))


def test_missing_api_key_file_raises(tmp_path: Path) -> None:
    with pytest.raises(RuntimeError, match="groq_api_key.txt"):
        GroqICLBot("P1", api_key_path=tmp_path / "groq_api_key.txt").select_move(
            make_obs(["3C", "QC"])
        )


def test_empty_api_key_file_raises(tmp_path: Path) -> None:
    path = tmp_path / "groq_api_key.txt"
    path.write_text("  \n", encoding="utf-8")
    with pytest.raises(RuntimeError, match="empty"):
        read_api_key(path)


def test_api_key_is_read_from_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = tmp_path / "groq_api_key.txt"
    path.write_text("  'gsk_test'  \n", encoding="utf-8")
    seen: list[str] = []

    def fake_groq(*, api_key: str) -> FakeClient:
        seen.append(api_key)
        return FakeClient('{"card": "QC"}')

    monkeypatch.setattr("groq.Groq", fake_groq)
    move = GroqICLBot("P1", api_key_path=path).select_move(make_obs(["3C", "QC"]))
    assert move == "QC"
    assert seen == ["gsk_test"]


def test_prompt_contains_rules_state_examples_and_legal_reminder(tmp_path: Path) -> None:
    path = tmp_path / "trajectories.jsonl"
    write_trajectories(path, 5)
    client = FakeClient('{"card": "3C"}')
    bot = GroqICLBot("P1", trajectories_path=path, num_examples=2, client=client)
    obs = make_obs(["3C", "QC", "AC"])
    bot.select_move(obs)

    system, user = client.calls[0]["messages"]
    assert system["role"] == "system" and user["role"] == "user"
    assert "Hearts" in system["content"] and "Queen of Spades" in system["content"]
    assert "P1" in system["content"]

    content = user["content"]
    assert obs.to_icl_prompt() in content
    assert "ONLY from this list of legal moves: 3C, QC, AC" in content
    # Last two informative examples only; forced move skipped.
    assert "EXAMPLE-4" in content and "EXAMPLE-3" in content
    assert "EXAMPLE-2" not in content
    assert "FORCED-EXAMPLE" not in content
    assert 'Answer: {"card": "9C"}' in content


def test_random_example_selection_is_seeded(tmp_path: Path) -> None:
    path = tmp_path / "trajectories.jsonl"
    write_trajectories(path, 20)
    obs = make_obs(["3C", "QC"])

    def user_prompt(seed: int) -> str:
        bot = GroqICLBot(
            "P1",
            trajectories_path=path,
            num_examples=3,
            example_selection="random",
            client=FakeClient(),
            seed=seed,
        )
        return bot.build_messages(obs)[1]["content"]

    assert user_prompt(7) == user_prompt(7)


def test_missing_trajectory_file_is_ignored(tmp_path: Path) -> None:
    bot = GroqICLBot("P1", trajectories_path=tmp_path / "nope.jsonl", client=FakeClient())
    content = bot.build_messages(make_obs(["3C", "QC"]))[1]["content"]
    assert "Example" not in content


def test_invalid_example_selection_rejected() -> None:
    with pytest.raises(ValueError):
        GroqICLBot("P1", example_selection="newest")  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ('{"card": "qc"}', "QC"),
        ('Sure! ```json\n{"card": "3C"}\n```', "3C"),
        ("Play QC.", "QC"),
        ("Not 3C, rather QC", "QC"),
        ('{"card": "10C"}', None),
        ("nothing", None),
    ],
)
def test_parse_card(text: str, expected: str | None) -> None:
    assert parse_card(text, ["3C", "QC", "AC"]) == expected
