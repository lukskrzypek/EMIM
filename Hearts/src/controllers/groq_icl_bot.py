"""LLM controller: In-Context Learning over the Groq API (few-shot from trajectories)."""

from __future__ import annotations

import json
import logging
import random
import re
from collections import deque
from pathlib import Path
from typing import Any, Literal

from controllers.base import PlayerController
from engine.game import PlayerObservation

logger = logging.getLogger(__name__)

DEFAULT_MODEL = "openai/gpt-oss-20b"
DEFAULT_API_KEY_PATH = Path(__file__).resolve().parents[2] / "groq_api_key.txt"
DEFAULT_EXCHANGE_LOG_PATH = Path(__file__).resolve().parents[2] / "logs" / "groq_exchanges.jsonl"
DEFAULT_ILLEGAL_LOG_PATH = Path(__file__).resolve().parents[2] / "logs" / "groq_illegal_moves.jsonl"
DEFAULT_MEMORY_DIR = Path(__file__).resolve().parents[2] / "logs"

_CARD_RE = re.compile(r"\b[2-9TJQKA][CDSH]\b")
_CARD_KEY_RE = re.compile(r'"card"\s*:\s*"([2-9TJQKA][CDHS])"', re.IGNORECASE)
_JSON_RE = re.compile(r"\{.*?\}", re.DOTALL)
_MAX_POOL = 500  # newest informative trajectory records kept as example candidates
# Room for a low-effort chain of thought plus a memory pad. 512 cut the JSON
# off inside ``memory``, after a legal ``card`` had already been written.
DEFAULT_MAX_TOKENS = 4096

SYSTEM_PROMPT = """\
Expert Hearts player. Cards: rank (2-9,T,J,Q,K,A) + suit (C,D,S,H).
Goal: minimize penalty points (H=1pt, QS=13pt; all 26pts = Shoot the Moon: 0 for you, 26 others).
Heuristics: duck when following suit; dump QS and high H/S when void; lead low from long suits; track Voids.
MEMORY PAD: Your scratchpad is saved to disk and loaded on every later run. Update it on most turns with compact notes on moves, strategy, or opponent reads. When the pad is full, edit it: drop stale notes and keep what still matters instead of returning null.
Reply ONLY with JSON: {"card": "<CODE from Legal>", "reasoning": "<short>", "memory": "<rewritten pad, or null only if nothing changed>"}"""


def _load_examples(
    path: Path,
    count: int,
    selection: Literal["last", "random"],
    rng: random.Random,
) -> list[dict[str, Any]]:
    """Read informative records (more than one legal move) from a JSONL file."""
    if count <= 0 or not path.is_file():
        return []
    pool: deque[dict[str, Any]] = deque(maxlen=_MAX_POOL)
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            legal = record.get("legal_moves")
            if (
                isinstance(legal, list)
                and len(legal) > 1
                and record.get("chosen_move") in legal
                and record.get("prompt_context")
            ):
                pool.append(record)
    records = list(pool)
    if selection == "random":
        return rng.sample(records, min(count, len(records)))
    return records[-count:]


def _format_example(index: int, record: dict[str, Any]) -> str:
    lines = [f"### Example {index}", str(record["prompt_context"])]
    reasoning = str(record.get("reasoning") or "").strip()
    if reasoning:
        lines.append(f"Reasoning: {reasoning}")
    lines.append(f"Answer: {json.dumps({'card': record['chosen_move']})}")
    return "\n".join(lines)


def read_api_key(path: Path) -> str:
    """Return the key from the first non-empty line of ``path``."""
    if not path.is_file():
        raise RuntimeError(f"Put the Groq API key in {path} (one line).")
    for line in path.read_text(encoding="utf-8").splitlines():
        key = line.strip().strip('"').strip("'")
        if key:
            return key
    raise RuntimeError(f"{path} is empty.")


def _json_card(text: str) -> str | None:
    """Last ``{"card": "..."}`` value in ``text``, still unvalidated."""
    found: str | None = None
    for blob in _JSON_RE.findall(text):
        try:
            data = json.loads(blob)
        except json.JSONDecodeError:
            continue
        if isinstance(data, dict) and isinstance(data.get("card"), str):
            found = data["card"]
    return found


def _json_reasoning(text: str) -> str:
    """Last ``reasoning`` string from a JSON object in ``text``."""
    found = ""
    for blob in _JSON_RE.findall(text):
        try:
            data = json.loads(blob)
        except json.JSONDecodeError:
            continue
        if isinstance(data, dict) and isinstance(data.get("reasoning"), str):
            found = data["reasoning"].strip()
    return found


def _json_memory(text: str) -> str | None:
    """Last non-empty ``memory`` string from a JSON object in ``text``.

    ``null`` and blank strings are ignored, so the pad stays as it is.
    """
    found: str | None = None
    for blob in _JSON_RE.findall(text):
        try:
            data = json.loads(blob)
        except json.JSONDecodeError:
            continue
        if isinstance(data, dict) and isinstance(data.get("memory"), str):
            memory = data["memory"].strip()
            if memory:
                found = memory
    return found


def decision_reasoning(message: Any, text: str) -> str:
    """Chain of thought from the API, or the JSON ``reasoning`` field."""
    chain = ""
    if not isinstance(message, str):
        raw = getattr(message, "reasoning", None) or ""
        if isinstance(raw, str):
            chain = raw.strip()
    return chain or _json_reasoning(text)


def _card_key(text: str) -> str | None:
    """``"card"`` value, including one left behind when JSON was cut off."""
    match = _CARD_KEY_RE.search(text)
    if match is None:
        return None
    return match.group(1).upper()


def _normalize_card(raw: str) -> str:
    return raw.strip().upper().replace("10", "T")


def parse_card(text: str, legal_moves: list[str]) -> str | None:
    """Chosen card, or ``None`` when the caller should play the first legal move.

    A finished JSON object wins. If the reply was cut off inside ``memory``,
    the ``"card"`` key is read directly and the rest of the text is ignored:
    the last card token is usually a hand or history dump. Prose with no
    JSON object still uses the last card token.
    """
    raw = _json_card(text)
    if raw is None:
        raw = _card_key(text)
    if raw is not None:
        candidate = _normalize_card(raw)
        return candidate if candidate in legal_moves else None
    if "{" in text:
        return None
    tokens = _CARD_RE.findall(text.upper().replace("10", "T"))
    if not tokens:
        return None
    return tokens[-1] if tokens[-1] in legal_moves else None


def _attempted_card(text: str) -> str | None:
    """Card the model named, including one that is not a legal move.

    A truncated object does not contribute a card from later in the dump.
    """
    raw = _json_card(text) or _card_key(text)
    if raw is None:
        if "{" in text:
            return None
        tokens = _CARD_RE.findall(text.upper().replace("10", "T"))
        raw = tokens[-1] if tokens else None
    if raw is None:
        return None
    return _normalize_card(raw)


def decision_response_format(legal_moves: list[str]) -> dict[str, Any]:
    """Strict schema: ``card`` is constrained to ``legal_moves``."""
    return {
        "type": "json_schema",
        "json_schema": {
            "name": "hearts_move",
            "strict": True,
            "schema": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "card": {"type": "string", "enum": list(legal_moves)},
                    "reasoning": {"type": "string"},
                    "memory": {"type": ["string", "null"]},
                },
                "required": ["card", "reasoning", "memory"],
            },
        },
    }


def reply_text(message: Any) -> str:
    """Text that holds the decision.

    Reasoning models spend the token budget on ``message.reasoning`` and leave
    ``content`` empty when generation is cut off. A finished answer is in
    ``content``; an explicit JSON card inside ``reasoning`` is the fallback.
    Cards merely mentioned in the reasoning prose are ignored.
    """
    if isinstance(message, str):
        return message
    content = getattr(message, "content", None) or ""
    if isinstance(content, str) and content.strip():
        return content
    reasoning = getattr(message, "reasoning", None) or ""
    if not isinstance(reasoning, str):
        return ""
    card = _json_card(reasoning) or _card_key(reasoning)
    if not card:
        return ""
    payload: dict[str, Any] = {"card": card}
    memory = _json_memory(reasoning)
    if memory:
        payload["memory"] = memory
    return json.dumps(payload)


class GroqICLBot(PlayerController):
    """Plays one seat by prompting a Groq-hosted LLM with few-shot examples."""

    def __init__(
        self,
        player_id: str,
        model: str = DEFAULT_MODEL,
        trajectories_path: str | Path | None = None,
        *,
        num_examples: int = 0,
        example_selection: Literal["last", "random"] = "last",
        temperature: float = 0.0,
        max_tokens: int = DEFAULT_MAX_TOKENS,
        api_key: str | None = None,
        api_key_path: str | Path | None = None,
        exchange_log_path: str | Path | None = None,
        illegal_log_path: str | Path | None = None,
        memory_path: str | Path | None = None,
        max_memory_chars: int = 600,
        client: Any | None = None,
        seed: int | None = None,
    ) -> None:
        if example_selection not in ("last", "random"):
            raise ValueError(f"example_selection must be 'last' or 'random', got {example_selection!r}")
        self.player_id = player_id
        self.model = model
        self.trajectories_path = Path(trajectories_path) if trajectories_path else None
        self._num_examples = num_examples
        self._selection: Literal["last", "random"] = example_selection
        self._temperature = temperature
        self._max_tokens = max_tokens
        self._api_key = api_key
        self._api_key_path = Path(api_key_path) if api_key_path is not None else DEFAULT_API_KEY_PATH
        # None means the project log. Tests can point the default at nothing.
        chosen_log = DEFAULT_EXCHANGE_LOG_PATH if exchange_log_path is None else exchange_log_path
        self._exchange_log_path = Path(chosen_log) if chosen_log else None
        chosen_illegal = DEFAULT_ILLEGAL_LOG_PATH if illegal_log_path is None else illegal_log_path
        self._illegal_log_path = Path(chosen_illegal) if chosen_illegal else None
        # None means logs/memory_<seat>.txt. "" or False keeps the pad off disk.
        chosen_memory = (
            DEFAULT_MEMORY_DIR / f"memory_{player_id}.txt" if memory_path is None else memory_path
        )
        self._memory_path = Path(chosen_memory) if chosen_memory else None
        self._max_memory_chars = max_memory_chars
        self._client = client
        self._rng = random.Random(seed)

    # ------------------------------------------------------------------ API

    def _get_client(self) -> Any:
        """Create the Groq SDK client lazily (needs ``groq`` and ``groq_api_key.txt``)."""
        if self._client is None:
            key = self._api_key if self._api_key is not None else read_api_key(self._api_key_path)
            try:
                from groq import Groq
            except ImportError as exc:  # pragma: no cover - depends on environment
                raise RuntimeError("Install the Groq SDK: pip install groq") from exc
            self._client = Groq(api_key=key)
        return self._client

    # --------------------------------------------------------------- prompts

    def build_messages(self, observation: PlayerObservation) -> list[dict[str, str]]:
        """System + user messages for the current observation."""
        examples = (
            _load_examples(self.trajectories_path, self._num_examples, self._selection, self._rng)
            if self.trajectories_path is not None and self._num_examples > 0
            else []
        )
        parts: list[str] = []
        if examples:
            parts.append("Past plays showing the expected format and decision style:")
            parts.extend(_format_example(i, rec) for i, rec in enumerate(examples, start=1))
        mem = self.read_memory()
        parts.append(f"### Your Memory Pad ({len(mem)}/{self._max_memory_chars} chars)\n{mem}")
        parts.append("### Current state (you are " + observation.player_id + ")")
        parts.append(observation.to_icl_prompt())
        system = SYSTEM_PROMPT + f"\n\nYou are player {self.player_id}."
        return [
            {"role": "system", "content": system},
            {"role": "user", "content": "\n\n".join(parts)},
        ]

    # ------------------------------------------------------------ controller

    def select_move(self, observation: PlayerObservation) -> str:
        legal = observation.legal_moves
        if not legal:
            raise ValueError(f"{observation.player_id} has no legal moves")
        if observation.player_id != self.player_id:
            raise ValueError(
                f"Bot controls {self.player_id}, but observation is for {observation.player_id}"
            )
        self.last_reasoning = ""
        if len(legal) == 1:
            return legal[0]

        client = self._get_client()
        request: dict[str, Any] = {
            "model": self.model,
            "messages": self.build_messages(observation),
            "temperature": self._temperature,
            "max_tokens": self._max_tokens,
            "response_format": decision_response_format(legal),
        }
        # gpt-oss writes a long chain of thought first. "low" leaves room
        # for the JSON answer in content. The thought stays on message.reasoning.
        if "gpt-oss" in self.model:
            request["reasoning_effort"] = "low"
        try:
            response = client.chat.completions.create(**request)
            message = response.choices[0].message
            text = reply_text(message)
            self.last_reasoning = decision_reasoning(message, text)
        except Exception as exc:  # network / API / quota errors must not stop the game
            logger.warning("Groq request failed (%s); playing first legal move", exc)
            self.last_reasoning = f"request failed: {exc}"
            self._log_exchange(request, None, legal[0], error=str(exc))
            self._log_illegal(
                kind="api",
                legal_moves=legal,
                fallback_move=legal[0],
                error=str(exc),
            )
            return legal[0]

        memory = _json_memory(text)
        if memory:
            self._write_memory(memory)

        move = parse_card(text, legal)
        if move is None:
            logger.warning("Illegal or unparsable Groq reply %r; playing first legal move", text)
            if not self.last_reasoning:
                self.last_reasoning = text.strip()
            attempted = _attempted_card(text)
            self._log_illegal(
                kind="illegal" if attempted else "unparsable",
                legal_moves=legal,
                fallback_move=legal[0],
                reply=text,
                attempted_card=attempted,
            )
            move = legal[0]
        self._log_exchange(request, message, move)
        return move

    def read_memory(self) -> str:
        """Last ``max_memory_chars`` of the scratchpad, or ``(empty)`` if there is no file."""
        if self._memory_path is None or not self._memory_path.is_file():
            return "(empty)"
        text = self._memory_path.read_text(encoding="utf-8")
        if len(text) > self._max_memory_chars:
            return text[-self._max_memory_chars :]
        return text

    def _write_memory(self, new_text: str) -> None:
        """Replace the scratchpad with ``new_text``, capped at ``max_memory_chars``."""
        if self._memory_path is None:
            return
        text = new_text.strip()[: self._max_memory_chars]
        self._memory_path.parent.mkdir(parents=True, exist_ok=True)
        self._memory_path.write_text(text, encoding="utf-8")

    def _log_illegal(
        self,
        *,
        kind: str,
        legal_moves: list[str],
        fallback_move: str,
        reply: str | None = None,
        attempted_card: str | None = None,
        error: str | None = None,
    ) -> None:
        """Append an API failure or a reply that was not a legal card."""
        if self._illegal_log_path is None:
            return
        record = {
            "player_id": self.player_id,
            "model": self.model,
            "kind": kind,
            "reply": reply,
            "attempted_card": attempted_card,
            "legal_moves": legal_moves,
            "fallback_move": fallback_move,
            "reasoning": self.last_reasoning,
            "error": error,
        }
        try:
            self._illegal_log_path.parent.mkdir(parents=True, exist_ok=True)
            with self._illegal_log_path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(record, ensure_ascii=False) + "\n")
        except OSError as exc:
            logger.warning("Could not write Groq illegal-move log (%s)", exc)

    def _log_exchange(
        self,
        request: dict[str, Any],
        message: Any | None,
        chosen_move: str,
        *,
        error: str | None = None,
    ) -> None:
        """Append the prompt sent to Groq and the raw reply. Never includes the API key."""
        if self._exchange_log_path is None:
            return
        if message is None:
            response: dict[str, str] | None = None
        elif isinstance(message, str):
            response = {"content": message, "reasoning": ""}
        else:
            content = getattr(message, "content", None) or ""
            reasoning = getattr(message, "reasoning", None) or ""
            response = {
                "content": content if isinstance(content, str) else str(content),
                "reasoning": reasoning if isinstance(reasoning, str) else str(reasoning),
            }
        record = {
            "player_id": self.player_id,
            "model": request.get("model", self.model),
            "messages": request.get("messages", []),
            "response": response,
            "chosen_move": chosen_move,
            "memory_after": self.read_memory(),
            "error": error,
        }
        try:
            self._exchange_log_path.parent.mkdir(parents=True, exist_ok=True)
            with self._exchange_log_path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(record, ensure_ascii=False) + "\n")
        except OSError as exc:
            logger.warning("Could not write Groq exchange log (%s)", exc)
