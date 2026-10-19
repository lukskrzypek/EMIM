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

_CARD_RE = re.compile(r"\b[2-9TJQKA][CDSH]\b")
_JSON_RE = re.compile(r"\{.*?\}", re.DOTALL)
_MAX_POOL = 500  # newest informative trajectory records kept as example candidates

SYSTEM_PROMPT = """\
You are an expert Hearts card player. Cards use 2-char notation: rank \
(2-9, T, J, Q, K, A; low to high) + suit (C clubs, D diamonds, S spades, H hearts).

Rules:
- Goal: finish the deal with as FEW penalty points as possible. Each heart = 1 point, \
the Queen of Spades (QS) = 13 points. Taking all 26 points ("shooting the moon") gives \
you 0 and everyone else 26.
- You must follow the led suit if you can. If you cannot, you may play any legal card.
- The player with the highest card of the led suit wins the trick, collects its points \
and leads next.
- Hearts cannot be led until broken (unless only hearts are held).

Strategy:
- When following suit, duck: play the highest card that is still lower than the highest \
card on the table, so you do not win a trick with points.
- If you cannot follow suit, dump dangerous cards: QS first, then the highest hearts \
(and AS/KS while QS is still out).
- When leading, avoid hearts and spades (until QS is gone); lead low cards of your longest \
suit to create voids.
- Use the history and the Voids line to infer where dangerous cards are.

Output format: reply with ONLY a JSON object \
{"card": "<CODE>", "reasoning": "<one short sentence>"}, where <CODE> is exactly \
one entry from the Legal list of the current state. No other text."""


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


def decision_reasoning(message: Any, text: str) -> str:
    """Chain of thought from the API, or the JSON ``reasoning`` field."""
    chain = ""
    if not isinstance(message, str):
        raw = getattr(message, "reasoning", None) or ""
        if isinstance(raw, str):
            chain = raw.strip()
    return chain or _json_reasoning(text)


def parse_card(text: str, legal_moves: list[str]) -> str | None:
    """Extract the chosen card from a model reply; ``None`` if not a legal move."""
    raw = _json_card(text)
    if raw is None:
        tokens = _CARD_RE.findall(text.upper().replace("10", "T"))
        raw = tokens[-1] if tokens else None
    if raw is None:
        return None
    candidate = raw.strip().upper().replace("10", "T")
    return candidate if candidate in legal_moves else None


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
    card = _json_card(reasoning)
    return json.dumps({"card": card}) if card else ""


class GroqICLBot(PlayerController):
    """Plays one seat by prompting a Groq-hosted LLM with few-shot examples."""

    def __init__(
        self,
        player_id: str,
        model: str = DEFAULT_MODEL,
        trajectories_path: str | Path | None = None,
        *,
        num_examples: int = 3,
        example_selection: Literal["last", "random"] = "last",
        temperature: float = 0.0,
        max_tokens: int = 512,
        api_key: str | None = None,
        api_key_path: str | Path | None = None,
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
            if self.trajectories_path is not None
            else []
        )
        parts: list[str] = []
        if examples:
            parts.append("Past plays showing the expected format and decision style:")
            parts.extend(_format_example(i, rec) for i, rec in enumerate(examples, start=1))
        parts.append("### Current state (you are " + observation.player_id + ")")
        parts.append(observation.to_icl_prompt())
        parts.append(
            "Choose exactly one card, and ONLY from this list of legal moves: "
            + ", ".join(observation.legal_moves)
        )
        parts.append('Reply with only JSON: {"card": "<CODE>", "reasoning": "<one short sentence>"}')
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
        try:
            request: dict[str, Any] = {
                "model": self.model,
                "messages": self.build_messages(observation),
                "temperature": self._temperature,
                "max_tokens": self._max_tokens,
            }
            # gpt-oss writes a long chain of thought first. "low" leaves room
            # for the JSON answer in content. The thought stays on message.reasoning.
            if "gpt-oss" in self.model:
                request["reasoning_effort"] = "low"
            response = client.chat.completions.create(**request)
            message = response.choices[0].message
            text = reply_text(message)
            self.last_reasoning = decision_reasoning(message, text)
        except Exception as exc:  # network / API / quota errors must not stop the game
            logger.warning("Groq request failed (%s); playing first legal move", exc)
            self.last_reasoning = f"request failed: {exc}"
            return legal[0]

        move = parse_card(text, legal)
        if move is None:
            logger.warning("Illegal or unparsable Groq reply %r; playing first legal move", text)
            if not self.last_reasoning:
                self.last_reasoning = text.strip()
            return legal[0]
        return move
