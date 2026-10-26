"""GroqICLBot tests: the Groq API is mocked, no key or network needed."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from controllers.base import PlayerController
from controllers.groq_icl_bot import (
    DEFAULT_MAX_TOKENS,
    DEFAULT_MODEL,
    GroqICLBot,
    parse_card,
    read_api_key,
)
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


@pytest.fixture(autouse=True)
def _no_project_illegal_log(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep unit tests from appending to logs/groq_illegal_moves.jsonl."""
    monkeypatch.setattr("controllers.groq_icl_bot.DEFAULT_ILLEGAL_LOG_PATH", None)


@pytest.fixture(autouse=True)
def _no_project_memory(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Keep unit tests away from logs/memory_*.txt."""
    monkeypatch.setattr("controllers.groq_icl_bot.DEFAULT_MEMORY_DIR", tmp_path / "default_mem")


def test_is_player_controller() -> None:
    assert isinstance(GroqICLBot("P1", client=FakeClient()), PlayerController)


def test_default_model() -> None:
    assert GroqICLBot("P1", client=FakeClient()).model == DEFAULT_MODEL


def test_returns_card_from_json_reply() -> None:
    client = FakeClient('{"card": "QC"}')
    bot = GroqICLBot("P1", client=client)
    legal = ["3C", "QC", "AC"]
    assert bot.select_move(make_obs(legal)) == "QC"
    assert len(client.calls) == 1
    call = client.calls[0]
    assert call["model"] == DEFAULT_MODEL
    assert call["reasoning_effort"] == "low"
    assert call["max_tokens"] == DEFAULT_MAX_TOKENS
    schema = call["response_format"]["json_schema"]
    assert schema["strict"] is True
    assert schema["schema"]["properties"]["card"]["enum"] == legal
    assert schema["schema"]["additionalProperties"] is False


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
    assert "Hearts" in system["content"] and "QS" in system["content"]
    assert "P1" in system["content"]

    content = user["content"]
    assert obs.to_icl_prompt() in content
    assert "### Current state (you are P1)" in content
    assert "Choose exactly one card" not in content
    assert "Reply with only JSON" not in content
    # Last two informative examples only; forced move skipped.
    assert "EXAMPLE-4" in content and "EXAMPLE-3" in content
    assert "EXAMPLE-2" not in content
    assert "FORCED-EXAMPLE" not in content
    assert 'Answer: {"card": "9C"}' in content


def test_num_examples_defaults_to_zero(tmp_path: Path) -> None:
    path = tmp_path / "trajectories.jsonl"
    write_trajectories(path, 5)
    bot = GroqICLBot("P1", trajectories_path=path, client=FakeClient())
    content = bot.build_messages(make_obs(["3C", "QC"]))[1]["content"]
    assert "Example" not in content
    assert "EXAMPLE-" not in content


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


def test_truncated_json_keeps_the_card_key_not_the_dump() -> None:
    text = '{"card": "3C", "reasoning": "duck", "memory": "Hand: QH TS history T1 P0:5C'
    assert parse_card(text, ["3C", "5C", "QC"]) == "3C"


def test_truncated_illegal_card_key_is_not_replaced_by_a_later_token() -> None:
    text = '{"card": "QH", "memory": "TS 3C'
    assert parse_card(text, ["3C", "5C"]) is None


def test_truncated_object_without_a_card_key_is_not_scraped() -> None:
    text = '{"reasoning": "duck", "memory": "Hand: QH TS 3C'
    assert parse_card(text, ["3C", "5C", "QC"]) is None


def test_select_move_plays_card_from_truncated_json() -> None:
    reply = '{"card": "5C", "reasoning": "duck", "memory": "Hand: QH TS 3C'
    client = FakeClient(reply)
    assert GroqICLBot("P1", client=client).select_move(make_obs(["3C", "5C", "QC"])) == "5C"


def test_truncated_card_key_in_reasoning_is_a_move() -> None:
    message = SimpleNamespace(content="", reasoning='Weighing.\n{"card": "5C", "memory": "QH TS')
    client = FakeClient()
    client._reply = message  # type: ignore[assignment]
    assert GroqICLBot("P1", client=client).select_move(make_obs(["3C", "5C", "QC"])) == "5C"


def test_truncated_illegal_card_key_is_logged(tmp_path: Path) -> None:
    path = tmp_path / "groq_illegal_moves.jsonl"
    reply = '{"card": "QH", "memory": "TS 3C'
    bot = GroqICLBot("P1", client=FakeClient(reply), illegal_log_path=path)
    assert bot.select_move(make_obs(["3C", "5C"])) == "3C"
    record = json.loads(path.read_text(encoding="utf-8"))
    assert record["kind"] == "illegal"
    assert record["attempted_card"] == "QH"
    assert record["fallback_move"] == "3C"


def test_memory_is_injected_into_prompt(tmp_path: Path) -> None:
    mem = tmp_path / "mem.txt"
    mem.write_text("P0 void in hearts", encoding="utf-8")
    bot = GroqICLBot("P1", client=FakeClient(), memory_path=mem, max_memory_chars=600)
    content = bot.build_messages(make_obs(["3C", "QC"]))[1]["content"]
    assert "### Your Memory Pad (17/600 chars)\nP0 void in hearts" in content
    assert content.index("### Your Memory Pad") < content.index("### Current state")


def test_missing_memory_shows_empty(tmp_path: Path) -> None:
    bot = GroqICLBot("P1", client=FakeClient(), memory_path=tmp_path / "none.txt")
    assert bot.read_memory() == "(empty)"
    assert "(empty)" in bot.build_messages(make_obs(["3C", "QC"]))[1]["content"]


def test_default_memory_path_is_per_model(tmp_path: Path) -> None:
    bot = GroqICLBot(
        "P1", model="openai/gpt-oss-120b", client=FakeClient('{"card": "QC", "memory": "hi"}')
    )
    bot.select_move(make_obs(["3C", "QC"]))
    pad = tmp_path / "default_mem" / "memory_openai_gpt-oss-120b.txt"
    assert pad.read_text(encoding="utf-8") == "hi"
    # Same model at another seat keeps the same pad; a different model gets its own file.
    assert GroqICLBot("P0", model="openai/gpt-oss-120b", client=FakeClient()).read_memory() == "hi"
    other = GroqICLBot("P0", model="other/model", client=FakeClient('{"card": "QC", "memory": "there"}'))
    other.select_move(make_obs(["3C", "QC"], player_id="P0"))
    assert (tmp_path / "default_mem" / "memory_other_model.txt").read_text(encoding="utf-8") == "there"


@pytest.mark.parametrize("disabled", ["", False])
def test_memory_can_be_disabled(disabled: Any, tmp_path: Path) -> None:
    bot = GroqICLBot("P1", client=FakeClient('{"card": "QC", "memory": "hi"}'), memory_path=disabled)
    assert bot.select_move(make_obs(["3C", "QC"])) == "QC"
    assert bot.read_memory() == "(empty)"
    assert not (tmp_path / "default_mem").exists()


def test_model_overwrites_memory(tmp_path: Path) -> None:
    mem = tmp_path / "mem.txt"
    mem.write_text("old", encoding="utf-8")
    client = FakeClient('{"card": "QC", "reasoning": "x", "memory": "nowa notatka"}')
    bot = GroqICLBot("P1", client=client, memory_path=mem)
    assert bot.select_move(make_obs(["3C", "QC"])) == "QC"
    assert mem.read_text(encoding="utf-8") == "nowa notatka"


def test_null_memory_keeps_file(tmp_path: Path) -> None:
    mem = tmp_path / "mem.txt"
    mem.write_text("old", encoding="utf-8")
    client = FakeClient('{"card": "QC", "memory": null}')
    bot = GroqICLBot("P1", client=client, memory_path=mem)
    assert bot.select_move(make_obs(["3C", "QC"])) == "QC"
    assert mem.read_text(encoding="utf-8") == "old"


def test_long_memory_is_trimmed(tmp_path: Path) -> None:
    mem = tmp_path / "sub" / "mem.txt"
    client = FakeClient(json.dumps({"card": "QC", "memory": "  " + "a" * 50 + "  "}))
    bot = GroqICLBot("P1", client=client, memory_path=mem, max_memory_chars=10)
    bot.select_move(make_obs(["3C", "QC"]))
    assert mem.read_text(encoding="utf-8") == "a" * 10
    mem.write_text("0123456789ABCDEF", encoding="utf-8")
    assert bot.read_memory() == "6789ABCDEF"


def test_memory_in_reasoning_json_fallback(tmp_path: Path) -> None:
    mem = tmp_path / "mem.txt"
    message = SimpleNamespace(content="", reasoning='Thinking.\n{"card": "QC", "memory": "from cot"}')
    client = FakeClient()
    client._reply = message  # type: ignore[assignment]
    bot = GroqICLBot("P1", client=client, memory_path=mem)
    assert bot.select_move(make_obs(["3C", "QC"])) == "QC"
    assert mem.read_text(encoding="utf-8") == "from cot"


def test_exchange_log_stores_memory_after(tmp_path: Path) -> None:
    log = tmp_path / "log.jsonl"
    client = FakeClient('{"card": "QC", "memory": "note"}')
    bot = GroqICLBot("P1", client=client, exchange_log_path=log, memory_path=tmp_path / "m.txt")
    bot.select_move(make_obs(["3C", "QC"]))
    assert json.loads(log.read_text(encoding="utf-8"))["memory_after"] == "note"


def test_memory_persists_for_a_new_bot(tmp_path: Path) -> None:
    mem = tmp_path / "memory_openai_gpt-oss-120b.txt"
    first = GroqICLBot(
        "P0",
        client=FakeClient('{"card": "QC", "memory": "P1 void C"}'),
        memory_path=mem,
    )
    assert first.select_move(make_obs(["3C", "QC"], player_id="P0")) == "QC"
    nxt = GroqICLBot("P0", client=FakeClient(), memory_path=mem)
    assert nxt.read_memory() == "P1 void C"
    assert "P1 void C" in nxt.build_messages(make_obs(["3C", "QC"], player_id="P0"))[1]["content"]


def test_prompt_says_a_full_pad_can_be_edited() -> None:
    system = GroqICLBot("P1", client=FakeClient()).build_messages(make_obs(["3C"]))[0]["content"]
    assert "saved to disk" in system
    assert "When editing, prune expired hand details" in system


def test_illegal_card_is_logged(tmp_path: Path) -> None:
    path = tmp_path / "groq_illegal_moves.jsonl"
    client = FakeClient('{"card": "AS", "reasoning": "dump"}')
    bot = GroqICLBot("P1", client=client, illegal_log_path=path)
    assert bot.select_move(make_obs(["3C", "QC"])) == "3C"
    record = json.loads(path.read_text(encoding="utf-8"))
    assert record["player_id"] == "P1"
    assert record["kind"] == "illegal"
    assert record["attempted_card"] == "AS"
    assert record["legal_moves"] == ["3C", "QC"]
    assert record["fallback_move"] == "3C"
    assert record["error"] is None


def test_unparsable_reply_is_logged(tmp_path: Path) -> None:
    path = tmp_path / "groq_illegal_moves.jsonl"
    bot = GroqICLBot("P1", client=FakeClient("I think I will pass."), illegal_log_path=path)
    assert bot.select_move(make_obs(["3C", "QC"])) == "3C"
    record = json.loads(path.read_text(encoding="utf-8"))
    assert record["kind"] == "unparsable"
    assert record["attempted_card"] is None
    assert record["fallback_move"] == "3C"


def test_api_error_is_logged(tmp_path: Path) -> None:
    path = tmp_path / "groq_illegal_moves.jsonl"
    client = FakeClient(error=RuntimeError("rate limited"))
    bot = GroqICLBot("P1", client=client, illegal_log_path=path)
    assert bot.select_move(make_obs(["3C", "QC"])) == "3C"
    record = json.loads(path.read_text(encoding="utf-8"))
    assert record["kind"] == "api"
    assert record["reply"] is None
    assert record["error"] == "rate limited"
    assert record["fallback_move"] == "3C"


def test_legal_move_does_not_log_an_illegal(tmp_path: Path) -> None:
    path = tmp_path / "groq_illegal_moves.jsonl"
    bot = GroqICLBot("P1", client=FakeClient('{"card": "QC"}'), illegal_log_path=path)
    assert bot.select_move(make_obs(["3C", "QC"])) == "QC"
    assert not path.exists()


def test_default_illegal_log_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    log = tmp_path / "groq_illegal_moves.jsonl"
    monkeypatch.setattr("controllers.groq_icl_bot.DEFAULT_ILLEGAL_LOG_PATH", log)
    bot = GroqICLBot("P0", client=FakeClient('{"card": "AS"}'))
    assert bot.select_move(make_obs(["3C", "QC"], player_id="P0")) == "3C"
    assert json.loads(log.read_text(encoding="utf-8"))["attempted_card"] == "AS"
