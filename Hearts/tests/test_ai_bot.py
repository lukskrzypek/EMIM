"""AIBot tests: the API is mocked, no key or network needed."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from controllers.base import PlayerController
from controllers.ai_bot import (
    DEFAULT_MAX_TOKENS,
    DEFAULT_MODEL,
    AIBot,
    parse_card,
    read_api_key,
)
from engine.game import PlayerObservation


class FakeClient:
    """Mimics the Groq / OpenAI client: ``client.chat.completions.create(...)``."""

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
    """Keep unit tests from appending to logs/ai_exchanges.jsonl."""
    monkeypatch.setattr("controllers.ai_bot.DEFAULT_EXCHANGE_LOG_PATH", None)


@pytest.fixture(autouse=True)
def _no_project_illegal_log(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep unit tests from appending to logs/ai_illegal_moves.jsonl."""
    monkeypatch.setattr("controllers.ai_bot.DEFAULT_ILLEGAL_LOG_PATH", None)


@pytest.fixture(autouse=True)
def _no_project_api_error_log(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep unit tests from appending to logs/ai_api_errors.jsonl."""
    monkeypatch.setattr("controllers.ai_bot.DEFAULT_API_ERROR_LOG_PATH", None)


@pytest.fixture(autouse=True)
def _no_project_memory(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Keep unit tests away from logs/memory_*.txt."""
    monkeypatch.setattr("controllers.ai_bot.DEFAULT_MEMORY_DIR", tmp_path / "default_mem")


def test_is_player_controller() -> None:
    assert isinstance(AIBot("P1", client=FakeClient()), PlayerController)


def test_default_model() -> None:
    assert AIBot("P1", client=FakeClient()).model == DEFAULT_MODEL


def test_returns_card_from_json_reply() -> None:
    client = FakeClient('{"card": "QC"}')
    bot = AIBot("P1", client=client)
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
    assert AIBot("P1", client=client).select_move(make_obs(["3C"])) == "3C"
    assert client.calls == []


def test_illegal_card_falls_back_to_first_legal() -> None:
    client = FakeClient('{"card": "AS"}')
    assert AIBot("P1", client=client).select_move(make_obs(["3C", "QC"])) == "3C"


def test_empty_content_uses_json_card_from_reasoning() -> None:
    message = SimpleNamespace(content="", reasoning='Weighing 2C against QC.\n{"card": "QC"}')
    client = FakeClient()
    client._reply = message  # type: ignore[assignment]
    assert AIBot("P1", client=client).select_move(make_obs(["3C", "QC"])) == "QC"


def test_api_reasoning_is_kept_for_the_log() -> None:
    message = SimpleNamespace(content='{"card": "QC"}', reasoning="Duck under the king.")
    client = FakeClient()
    client._reply = message  # type: ignore[assignment]
    bot = AIBot("P1", client=client)
    assert bot.select_move(make_obs(["3C", "QC"])) == "QC"
    assert bot.last_reasoning == "Duck under the king."


def test_json_reasoning_is_kept_when_the_channel_is_empty() -> None:
    client = FakeClient('{"card": "QC", "reasoning": "safe duck"}')
    bot = AIBot("P1", client=client)
    assert bot.select_move(make_obs(["3C", "QC"])) == "QC"
    assert bot.last_reasoning == "safe duck"


def test_exchange_log_stores_prompt_and_reply(tmp_path: Path) -> None:
    path = tmp_path / "ai_exchanges.jsonl"
    client = FakeClient('{"card": "QC", "reasoning": "safe duck"}')
    bot = AIBot("P1", client=client, exchange_log_path=path)
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
    path = tmp_path / "ai_exchanges.jsonl"
    client = FakeClient(error=RuntimeError("rate limited"))
    bot = AIBot("P1", client=client, exchange_log_path=path)
    assert bot.select_move(make_obs(["3C", "QC"])) == "3C"
    record = json.loads(path.read_text(encoding="utf-8"))
    assert record["response"] is None
    assert record["error"] == "rate limited"
    assert record["messages"][1]["role"] == "user"


def test_single_legal_move_does_not_log_an_exchange(tmp_path: Path) -> None:
    path = tmp_path / "ai_exchanges.jsonl"
    bot = AIBot("P1", client=FakeClient('{"card": "3C"}'), exchange_log_path=path)
    assert bot.select_move(make_obs(["3C"])) == "3C"
    assert not path.exists()


def test_single_legal_move_clears_previous_reasoning() -> None:
    bot = AIBot("P1", client=FakeClient('{"card": "QC"}'))
    bot.last_reasoning = "stale"
    assert bot.select_move(make_obs(["3C"])) == "3C"
    assert bot.last_reasoning == ""


def test_reasoning_prose_without_json_is_not_a_move() -> None:
    message = SimpleNamespace(content="", reasoning="Maybe QC, but the table has 2C.")
    client = FakeClient()
    client._reply = message  # type: ignore[assignment]
    assert AIBot("P1", client=client).select_move(make_obs(["3C", "QC"])) == "3C"


def test_unparsable_reply_falls_back_to_first_legal() -> None:
    client = FakeClient("I think I will pass.")
    assert AIBot("P1", client=client).select_move(make_obs(["3C", "QC"])) == "3C"


def test_api_error_falls_back_to_first_legal() -> None:
    client = FakeClient(error=RuntimeError("rate limited"))
    assert AIBot("P1", client=client).select_move(make_obs(["3C", "QC"])) == "3C"


def test_wrong_player_id_raises() -> None:
    bot = AIBot("P0", client=FakeClient('{"card": "3C"}'))
    with pytest.raises(ValueError):
        bot.select_move(make_obs(["3C", "QC"], player_id="P1"))


def test_missing_api_key_file_raises(tmp_path: Path) -> None:
    with pytest.raises(RuntimeError, match="groq_api_key.txt"):
        AIBot("P1", api_key_path=tmp_path / "groq_api_key.txt").select_move(
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
    move = AIBot("P1", api_key_path=path).select_move(make_obs(["3C", "QC"]))
    assert move == "QC"
    assert seen == ["gsk_test"]


def test_prompt_contains_rules_state_examples_and_legal_reminder(tmp_path: Path) -> None:
    path = tmp_path / "trajectories.jsonl"
    write_trajectories(path, 5)
    client = FakeClient('{"card": "3C"}')
    bot = AIBot("P1", trajectories_path=path, num_examples=2, client=client)
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
    bot = AIBot("P1", trajectories_path=path, client=FakeClient())
    content = bot.build_messages(make_obs(["3C", "QC"]))[1]["content"]
    assert "Example" not in content
    assert "EXAMPLE-" not in content


def test_random_example_selection_is_seeded(tmp_path: Path) -> None:
    path = tmp_path / "trajectories.jsonl"
    write_trajectories(path, 20)
    obs = make_obs(["3C", "QC"])

    def user_prompt(seed: int) -> str:
        bot = AIBot(
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
    bot = AIBot("P1", trajectories_path=tmp_path / "nope.jsonl", client=FakeClient())
    content = bot.build_messages(make_obs(["3C", "QC"]))[1]["content"]
    assert "Example" not in content


def test_invalid_example_selection_rejected() -> None:
    with pytest.raises(ValueError):
        AIBot("P1", example_selection="newest")  # type: ignore[arg-type]


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
    assert AIBot("P1", client=client).select_move(make_obs(["3C", "5C", "QC"])) == "5C"


def test_truncated_card_key_in_reasoning_is_a_move() -> None:
    message = SimpleNamespace(content="", reasoning='Weighing.\n{"card": "5C", "memory": "QH TS')
    client = FakeClient()
    client._reply = message  # type: ignore[assignment]
    assert AIBot("P1", client=client).select_move(make_obs(["3C", "5C", "QC"])) == "5C"


def test_truncated_illegal_card_key_is_logged(tmp_path: Path) -> None:
    path = tmp_path / "ai_illegal_moves.jsonl"
    reply = '{"card": "QH", "memory": "TS 3C'
    bot = AIBot("P1", client=FakeClient(reply), illegal_log_path=path)
    assert bot.select_move(make_obs(["3C", "5C"])) == "3C"
    record = json.loads(path.read_text(encoding="utf-8"))
    assert record["kind"] == "illegal"
    assert record["attempted_card"] == "QH"
    assert record["fallback_move"] == "3C"


def test_memory_is_injected_into_prompt(tmp_path: Path) -> None:
    mem = tmp_path / "mem.txt"
    mem.write_text("P0 void in hearts", encoding="utf-8")
    bot = AIBot("P1", client=FakeClient(), memory_path=mem, max_memory_chars=600)
    content = bot.build_messages(make_obs(["3C", "QC"]))[1]["content"]
    assert "### Your Memory Pad (17/600 chars)\nP0 void in hearts" in content
    assert content.index("### Your Memory Pad") < content.index("### Current state")


def test_missing_memory_shows_empty(tmp_path: Path) -> None:
    bot = AIBot("P1", client=FakeClient(), memory_path=tmp_path / "none.txt")
    assert bot.read_memory() == "(empty)"
    assert "(empty)" in bot.build_messages(make_obs(["3C", "QC"]))[1]["content"]


def test_new_model_gets_its_own_memory_file_at_startup(tmp_path: Path) -> None:
    AIBot("P0", model="openai/gpt-oss-20b", client=FakeClient())
    pad = tmp_path / "default_mem" / "memory_openai_gpt-oss-20b.txt"
    assert pad.is_file() and pad.read_text(encoding="utf-8") == ""
    assert AIBot("P0", model="openai/gpt-oss-20b", client=FakeClient()).read_memory() == "(empty)"


def test_default_memory_path_is_per_model(tmp_path: Path) -> None:
    bot = AIBot(
        "P1", model="openai/gpt-oss-120b", client=FakeClient('{"card": "QC", "memory": "hi"}')
    )
    bot.select_move(make_obs(["3C", "QC"]))
    pad = tmp_path / "default_mem" / "memory_openai_gpt-oss-120b.txt"
    assert pad.read_text(encoding="utf-8") == "hi"
    # Same model at another seat keeps the same pad; a different model gets its own file.
    assert AIBot("P0", model="openai/gpt-oss-120b", client=FakeClient()).read_memory() == "hi"
    other = AIBot("P0", model="other/model", client=FakeClient('{"card": "QC", "memory": "there"}'))
    other.select_move(make_obs(["3C", "QC"], player_id="P0"))
    assert (tmp_path / "default_mem" / "memory_other_model.txt").read_text(encoding="utf-8") == "there"


@pytest.mark.parametrize("disabled", ["", False])
def test_memory_can_be_disabled(disabled: Any, tmp_path: Path) -> None:
    bot = AIBot("P1", client=FakeClient('{"card": "QC", "memory": "hi"}'), memory_path=disabled)
    assert bot.select_move(make_obs(["3C", "QC"])) == "QC"
    assert bot.read_memory() == "(empty)"
    assert not (tmp_path / "default_mem").exists()


def test_model_overwrites_memory(tmp_path: Path) -> None:
    mem = tmp_path / "mem.txt"
    mem.write_text("old", encoding="utf-8")
    client = FakeClient('{"card": "QC", "reasoning": "x", "memory": "nowa notatka"}')
    bot = AIBot("P1", client=client, memory_path=mem)
    assert bot.select_move(make_obs(["3C", "QC"])) == "QC"
    assert mem.read_text(encoding="utf-8") == "nowa notatka"


def test_null_memory_keeps_file(tmp_path: Path) -> None:
    mem = tmp_path / "mem.txt"
    mem.write_text("old", encoding="utf-8")
    client = FakeClient('{"card": "QC", "memory": null}')
    bot = AIBot("P1", client=client, memory_path=mem)
    assert bot.select_move(make_obs(["3C", "QC"])) == "QC"
    assert mem.read_text(encoding="utf-8") == "old"


def test_long_memory_is_trimmed(tmp_path: Path) -> None:
    mem = tmp_path / "sub" / "mem.txt"
    client = FakeClient(json.dumps({"card": "QC", "memory": "  " + "a" * 50 + "  "}))
    bot = AIBot("P1", client=client, memory_path=mem, max_memory_chars=10)
    bot.select_move(make_obs(["3C", "QC"]))
    assert mem.read_text(encoding="utf-8") == "a" * 10
    mem.write_text("0123456789ABCDEF", encoding="utf-8")
    assert bot.read_memory() == "6789ABCDEF"


def test_memory_in_reasoning_json_fallback(tmp_path: Path) -> None:
    mem = tmp_path / "mem.txt"
    message = SimpleNamespace(content="", reasoning='Thinking.\n{"card": "QC", "memory": "from cot"}')
    client = FakeClient()
    client._reply = message  # type: ignore[assignment]
    bot = AIBot("P1", client=client, memory_path=mem)
    assert bot.select_move(make_obs(["3C", "QC"])) == "QC"
    assert mem.read_text(encoding="utf-8") == "from cot"


def test_exchange_log_stores_memory_after(tmp_path: Path) -> None:
    log = tmp_path / "log.jsonl"
    client = FakeClient('{"card": "QC", "memory": "note"}')
    bot = AIBot("P1", client=client, exchange_log_path=log, memory_path=tmp_path / "m.txt")
    bot.select_move(make_obs(["3C", "QC"]))
    assert json.loads(log.read_text(encoding="utf-8"))["memory_after"] == "note"


def test_memory_persists_for_a_new_bot(tmp_path: Path) -> None:
    mem = tmp_path / "memory_openai_gpt-oss-120b.txt"
    first = AIBot(
        "P0",
        client=FakeClient('{"card": "QC", "memory": "P1 void C"}'),
        memory_path=mem,
    )
    assert first.select_move(make_obs(["3C", "QC"], player_id="P0")) == "QC"
    nxt = AIBot("P0", client=FakeClient(), memory_path=mem)
    assert nxt.read_memory() == "P1 void C"
    assert "P1 void C" in nxt.build_messages(make_obs(["3C", "QC"], player_id="P0"))[1]["content"]


def test_user_guidelines_are_appended_only_when_set(monkeypatch: pytest.MonkeyPatch) -> None:
    base = AIBot("P1", client=FakeClient()).build_messages(make_obs(["3C"]))[0]["content"]
    monkeypatch.setattr("controllers.ai_bot.USER_GUIDELINES", "Dump QS at the first void.")
    with_file = AIBot("P1", client=FakeClient()).build_messages(make_obs(["3C"]))[0]["content"]
    note = (
        "\n\nWhen choosing a card, the text below matters most. "
        "Prioritize it over every other guideline.\n"
    )
    assert with_file == base + note + "Dump QS at the first void."
    overridden = AIBot("P1", client=FakeClient(), guidelines="Lead clubs.")
    text = overridden.build_messages(make_obs(["3C"]))[0]["content"]
    assert text == base + note + "Lead clubs."
    cleared = AIBot("P1", client=FakeClient(), guidelines="  ")
    assert cleared.build_messages(make_obs(["3C"]))[0]["content"] == base


def test_prompt_says_a_full_pad_can_be_edited() -> None:
    system = AIBot("P1", client=FakeClient()).build_messages(make_obs(["3C"]))[0]["content"]
    assert "saved to disk" in system
    assert "When editing, prune expired hand details" in system
    assert "pad is not (empty)" in system


def test_illegal_card_is_logged(tmp_path: Path) -> None:
    path = tmp_path / "ai_illegal_moves.jsonl"
    client = FakeClient('{"card": "AS", "reasoning": "dump"}')
    bot = AIBot("P1", client=client, illegal_log_path=path)
    assert bot.select_move(make_obs(["3C", "QC"])) == "3C"
    record = json.loads(path.read_text(encoding="utf-8"))
    assert record["player_id"] == "P1"
    assert record["kind"] == "illegal"
    assert record["attempted_card"] == "AS"
    assert record["legal_moves"] == ["3C", "QC"]
    assert record["fallback_move"] == "3C"
    assert record["error"] is None


def test_unparsable_reply_is_logged(tmp_path: Path) -> None:
    path = tmp_path / "ai_illegal_moves.jsonl"
    bot = AIBot("P1", client=FakeClient("I think I will pass."), illegal_log_path=path)
    assert bot.select_move(make_obs(["3C", "QC"])) == "3C"
    record = json.loads(path.read_text(encoding="utf-8"))
    assert record["kind"] == "unparsable"
    assert record["attempted_card"] is None
    assert record["fallback_move"] == "3C"


def test_api_error_goes_to_its_own_log_not_the_illegal_move_log(tmp_path: Path) -> None:
    illegal, api = tmp_path / "ai_illegal_moves.jsonl", tmp_path / "ai_api_errors.jsonl"
    client = FakeClient(error=RuntimeError("rate limited"))
    bot = AIBot("P1", model="m/x", name="bold", client=client, illegal_log_path=illegal, api_error_log_path=api)
    assert bot.select_move(make_obs(["3C", "QC"])) == "3C"
    assert not illegal.exists()
    record = json.loads(api.read_text(encoding="utf-8"))
    assert record["player_id"] == "P1" and record["model"] == "m/x" and record["name"] == "bold"
    assert record["error"] == "rate limited" and record["status_code"] is None
    assert record["legal_moves"] == ["3C", "QC"] and record["fallback_move"] == "3C"
    assert "kind" not in record and "reply" not in record


def test_api_error_keeps_the_http_status_and_an_illegal_reply_stays_out_of_the_api_log(tmp_path: Path) -> None:
    illegal, api = tmp_path / "ill.jsonl", tmp_path / "api.jsonl"
    refused = FakeClient(error=ApiError("model_not_found", 404))
    AIBot("P1", client=refused, illegal_log_path=illegal, api_error_log_path=api).select_move(make_obs(["3C", "QC"]))
    assert json.loads(api.read_text(encoding="utf-8"))["status_code"] == 404

    api.unlink()
    AIBot("P1", client=FakeClient('{"card": "AS"}'), illegal_log_path=illegal, api_error_log_path=api).select_move(
        make_obs(["3C", "QC"])
    )
    assert not api.exists() and json.loads(illegal.read_text(encoding="utf-8"))["kind"] == "illegal"


def test_default_api_error_log_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    log = tmp_path / "ai_api_errors.jsonl"
    monkeypatch.setattr("controllers.ai_bot.DEFAULT_API_ERROR_LOG_PATH", log)
    bot = AIBot("P0", client=FakeClient(error=RuntimeError("boom")))
    assert bot.select_move(make_obs(["3C", "QC"], player_id="P0")) == "3C"
    assert json.loads(log.read_text(encoding="utf-8"))["error"] == "boom"


def test_legal_move_does_not_log_an_illegal(tmp_path: Path) -> None:
    path = tmp_path / "ai_illegal_moves.jsonl"
    bot = AIBot("P1", client=FakeClient('{"card": "QC"}'), illegal_log_path=path)
    assert bot.select_move(make_obs(["3C", "QC"])) == "QC"
    assert not path.exists()


def test_default_illegal_log_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    log = tmp_path / "ai_illegal_moves.jsonl"
    monkeypatch.setattr("controllers.ai_bot.DEFAULT_ILLEGAL_LOG_PATH", log)
    bot = AIBot("P0", client=FakeClient('{"card": "AS"}'))
    assert bot.select_move(make_obs(["3C", "QC"], player_id="P0")) == "3C"
    assert json.loads(log.read_text(encoding="utf-8"))["attempted_card"] == "AS"


def test_bot_name_marks_model_name_memory_file_and_logs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("controllers.ai_bot.DEFAULT_MEMORY_DIR", tmp_path)
    exchanges, illegal = tmp_path / "ex.jsonl", tmp_path / "ill.jsonl"
    plain = AIBot("P0", model="m/x", client=FakeClient('{"card": "QC"}'), exchange_log_path="", illegal_log_path="")
    named = AIBot(
        "P1", model="m/x", name=" bold ", client=FakeClient('{"card": "ZZ"}'),
        exchange_log_path=exchanges, illegal_log_path=illegal,
    )
    assert plain.model_name == "m/x" and plain.name == ""  # unnamed: exactly as before
    assert named.model_name == "m/x_bold" and named.model == "m/x"  # the API still gets the model id
    assert (tmp_path / "memory_m_x.txt").is_file() and (tmp_path / "memory_m_x_bold.txt").is_file()

    named.select_move(make_obs(["3C", "QC"]))
    assert named._label == "m/x_bold"
    for path in (exchanges, illegal):
        record = json.loads(path.read_text(encoding="utf-8"))
        assert record["model"] == "m/x" and record["name"] == "bold"
    assert named.build_messages(make_obs(["3C", "QC"]))  # prompts do not mention the name


# ----------------------------------------------------------------- other models (meta-llama ...)


class ScriptedClient(FakeClient):
    """Fails with the given errors first, then answers like ``FakeClient``."""

    def __init__(self, reply: str, errors: list[Exception]) -> None:
        super().__init__(reply)
        self._errors = list(errors)

    def _create(self, **kwargs: Any) -> Any:
        if self._errors:
            self.calls.append(kwargs)
            raise self._errors.pop(0)
        return super()._create(**kwargs)


class ApiError(Exception):
    def __init__(self, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.status_code = status_code


LLAMA = "meta-llama/llama-4-scout-17b-16e-instruct"


def test_non_gpt_oss_model_gets_plain_json_mode_and_no_reasoning_effort() -> None:
    client = FakeClient('Sure! ```json\n{"card": "QC", "reasoning": "duck", "memory": null}\n```')
    bot = AIBot("P1", model=LLAMA, client=client)
    assert bot.select_move(make_obs(["3C", "QC", "AC"])) == "QC"  # the fenced JSON is understood
    call = client.calls[0]
    assert call["model"] == LLAMA
    assert call["response_format"] == {"type": "json_object"}  # a strict schema is gpt-oss only
    assert "reasoning_effort" not in call
    assert bot.last_reasoning == "duck"


def test_llama_reply_with_an_illegal_card_still_falls_back() -> None:
    bot = AIBot("P1", model=LLAMA, client=FakeClient('{"card": "2H"}'))
    assert bot.select_move(make_obs(["3C", "QC"])) == "3C"


def test_format_refused_by_the_api_is_relaxed_and_remembered() -> None:
    refusal = ApiError("`response_format` of type `json_schema` is not supported with this model")
    client = ScriptedClient('{"card": "QC"}', [refusal])
    bot = AIBot("P1", client=client)  # gpt-oss: starts with the strict schema
    assert bot.select_move(make_obs(["3C", "QC"])) == "QC"
    assert client.calls[0]["response_format"]["type"] == "json_schema"
    assert client.calls[1]["response_format"] == {"type": "json_object"}

    bot.select_move(make_obs(["3C", "QC"]))
    assert client.calls[2]["response_format"] == {"type": "json_object"}  # not refused again


def test_format_is_dropped_when_json_mode_is_refused_too() -> None:
    errors = [ApiError("json_schema is not supported"), ApiError("json mode is not supported")]
    client = ScriptedClient('{"card": "QC"}', errors)
    bot = AIBot("P1", client=client)  # schema -> json mode -> nothing
    assert bot.select_move(make_obs(["3C", "QC"])) == "QC"
    assert len(client.calls) == 3 and "response_format" not in client.calls[2]
    assert not bot.last_reasoning.startswith("request failed")


def test_token_limit_of_the_model_is_learned() -> None:
    limit = ApiError("`max_tokens` must be less than or equal to `512`, the maximum value for ...")
    client = ScriptedClient('{"card": "QC"}', [limit])
    bot = AIBot("P1", model=LLAMA, client=client)
    assert bot.select_move(make_obs(["3C", "QC"])) == "QC"
    assert [c["max_tokens"] for c in client.calls] == [DEFAULT_MAX_TOKENS, 512]
    bot.select_move(make_obs(["3C", "QC"]))
    assert client.calls[-1]["max_tokens"] == 512


def test_other_api_errors_are_not_retried() -> None:
    for error in (ApiError("rate limit, max_tokens", 429), ApiError("model_not_found", 404), ApiError("boom")):
        client = ScriptedClient('{"card": "QC"}', [error, error, error])
        bot = AIBot("P1", model=LLAMA, client=client)
        assert bot.select_move(make_obs(["3C", "QC"])) == "3C"  # fallback, no retry
        assert len(client.calls) == 1
        assert bot.last_reasoning.startswith("request failed")


# ---------------------------------------------------------------------------- OpenAI


def openai_bot(model: str, client: FakeClient) -> AIBot:
    return AIBot("P1", model=model, provider="openai", client=client)


def test_unknown_provider_is_rejected() -> None:
    with pytest.raises(ValueError, match="provider"):
        AIBot("P1", provider="nope", client=FakeClient())


def test_provider_picks_the_default_model_key_file_and_log_field(tmp_path: Path) -> None:
    groq = AIBot("P1", client=FakeClient())
    assert groq.provider == "groq" and groq.model == DEFAULT_MODEL
    bot = AIBot("P1", provider="openai", client=FakeClient())
    assert bot.provider == "openai" and bot.model == "gpt-4o-mini"
    assert bot._api_key_path.name == "openai_api_key.txt"

    log = tmp_path / "log.jsonl"
    client = FakeClient('{"card": "QC"}')
    AIBot("P1", provider="openai", client=client, exchange_log_path=log).select_move(make_obs(["3C", "QC"]))
    assert json.loads(log.read_text(encoding="utf-8"))["provider"] == "openai"


def test_openai_uses_max_completion_tokens_and_the_strict_schema() -> None:
    client = FakeClient('{"card": "QC"}')
    assert openai_bot("gpt-4o-mini", client).select_move(make_obs(["3C", "QC"])) == "QC"
    call = client.calls[0]
    assert call["max_completion_tokens"] == DEFAULT_MAX_TOKENS and "max_tokens" not in call
    assert call["response_format"]["type"] == "json_schema"
    assert "reasoning_effort" not in call  # gpt-4o takes none


@pytest.mark.parametrize("model", ["gpt-5-mini", "o4-mini"])
def test_openai_reasoning_models_get_low_reasoning_effort(model: str) -> None:
    client = FakeClient('{"card": "QC"}')
    openai_bot(model, client).select_move(make_obs(["3C", "QC"]))
    assert client.calls[0]["reasoning_effort"] == "low"


def test_openai_refusal_of_temperature_and_reasoning_effort_is_remembered() -> None:
    errors = [
        ApiError("Unsupported value: 'temperature' does not support 0 with this model."),
        ApiError("Unsupported parameter: 'reasoning_effort' is not supported with this model."),
    ]
    client = ScriptedClient('{"card": "QC"}', errors)
    bot = openai_bot("gpt-5-mini", client)
    assert bot.select_move(make_obs(["3C", "QC"])) == "QC"
    assert "temperature" in client.calls[0] and "temperature" not in client.calls[1]
    assert "reasoning_effort" in client.calls[1] and "reasoning_effort" not in client.calls[2]

    bot.select_move(make_obs(["3C", "QC"]))
    assert "temperature" not in client.calls[-1] and "reasoning_effort" not in client.calls[-1]
    assert not bot.last_reasoning.startswith("request failed")


def test_openai_token_limit_is_learned() -> None:
    limit = ApiError("max_tokens is too large: 4096. This model supports at most 2048 completion tokens.")
    client = ScriptedClient('{"card": "QC"}', [limit])
    bot = openai_bot("gpt-4o-mini", client)
    assert bot.select_move(make_obs(["3C", "QC"])) == "QC"
    assert [c["max_completion_tokens"] for c in client.calls] == [DEFAULT_MAX_TOKENS, 2048]


def test_openai_client_is_built_with_the_key_from_its_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "openai_api_key.txt"
    path.write_text("sk-test\n", encoding="utf-8")
    seen: list[str] = []

    def fake_openai(*, api_key: str) -> FakeClient:
        seen.append(api_key)
        return FakeClient('{"card": "QC"}')

    monkeypatch.setattr("openai.OpenAI", fake_openai)
    bot = AIBot("P1", provider="openai", api_key_path=path)
    assert bot.select_move(make_obs(["3C", "QC"])) == "QC"
    assert seen == ["sk-test"]


def test_missing_openai_key_file_names_the_file(tmp_path: Path) -> None:
    bot = AIBot("P1", provider="openai", api_key_path=tmp_path / "openai_api_key.txt")
    with pytest.raises(RuntimeError, match="OpenAI API key in .*openai_api_key.txt"):
        bot.select_move(make_obs(["3C", "QC"]))