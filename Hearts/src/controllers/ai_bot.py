"""LLM controller: In-Context Learning over an OpenAI-compatible chat API (Groq or OpenAI)."""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from controllers.base import PlayerController
from engine.observation import PlayerObservation

logger = logging.getLogger(__name__)

_PROJECT_ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class Provider:
    """One API the bot can talk to: its SDK package, key file, model list file and default model."""

    id: str
    label: str
    package: str  # name of the pip package, which is also the import name
    key_path: Path
    models_path: Path
    default_model: str


PROVIDERS: dict[str, Provider] = {
    "groq": Provider(
        "groq", "Groq", "groq",
        _PROJECT_ROOT / "groq_api_key.txt", _PROJECT_ROOT / "groq_models.txt",
        "openai/gpt-oss-120b",
    ),
    "openai": Provider(
        "openai", "OpenAI", "openai",
        _PROJECT_ROOT / "openai_api_key.txt", _PROJECT_ROOT / "openai_models.txt",
        "gpt-4o-mini",
    ),
}
DEFAULT_PROVIDER = "groq"
DEFAULT_MODEL = PROVIDERS[DEFAULT_PROVIDER].default_model


def get_provider(provider: str) -> Provider:
    try:
        return PROVIDERS[provider]
    except KeyError:
        raise ValueError(f"Unknown provider {provider!r}; choose one of {', '.join(PROVIDERS)}") from None


DEFAULT_EXCHANGE_LOG_PATH = Path(__file__).resolve().parents[2] / "logs" / "ai_exchanges.jsonl"
DEFAULT_ILLEGAL_LOG_PATH = Path(__file__).resolve().parents[2] / "logs" / "ai_illegal_moves.jsonl"
# Requests the API refused (quota, unknown model, rate limit ...). Replies that came back but
# were no legal card go to the illegal-move log instead.
DEFAULT_API_ERROR_LOG_PATH = Path(__file__).resolve().parents[2] / "logs" / "ai_api_errors.jsonl"
DEFAULT_MEMORY_DIR = Path(__file__).resolve().parents[2] / "logs"

_CARD_RE = re.compile(r"\b[2-9TJQKA][CDSH]\b")
_CARD_KEY_RE = re.compile(r'"card"\s*:\s*"([2-9TJQKA][CDHS])"', re.IGNORECASE)
_JSON_RE = re.compile(r"\{.*?\}", re.DOTALL)
# Groq: "... less than or equal to `8192`"; OpenAI: "... supports at most 16384 completion tokens".
_TOKEN_LIMIT_RE = re.compile(r"(?:less than or equal to\s*`?|supports at most\s*)(\d+)")
# OpenAI reasoning models (o1, o3, gpt-5 ...) take reasoning_effort; gpt-4o and older do not.
_OPENAI_REASONING_RE = re.compile(r"^(o\d|gpt-5)", re.IGNORECASE)
# Words of a 400 that mean "this model does not take this response_format".
_FORMAT_ERROR_MARKERS = (
    "response_format",
    "json_schema",
    "json mode",
    "json_object",
    "structured output",
    "json_validate_failed",
    "failed to generate json",
)
# Room for a low-effort chain of thought plus a memory pad. 512 cut the JSON
# off inside ``memory``, after a legal ``card`` had already been written.
DEFAULT_MAX_TOKENS = 4096
# Optional extra instructions appended to the system prompt. Leave "" to add nothing.
# When set, the prompt says to follow them ahead of every other playing guideline.
USER_GUIDELINES = ""

SYSTEM_PROMPT = """\
Expert Kierki (King) player. Cards: rank (2-9,T,J,Q,K,A) + suit (C,D,S,H). Rank and suit are followed in Legal.
A game is 7 deals, one of each contract in this order (see the Rule line). Goal: lowest total penalty points.
Contracts: NO_TRICKS (each trick 20), NO_HEARTS (each heart 20), NO_QUEENS (each Q 60), NO_MEN (each K/J 30),
NO_KING_OF_HEARTS (KH 150), NO_7TH_AND_LAST (tricks 7 and last 75 each), ROBBER (all of them combined).
Heuristics: duck when following suit; dump penalty cards when void; lead low from long suits; track Voids.
MEMORY PAD: Your scratchpad is saved to disk across sessions. Use it for two distinct layers:
1. Current Hand: transient state, known Voids, and active trick tracking.
2. Long-term Playbook: cross-game heuristics, opponent profiles/tendencies, and lessons learned from past mistakes.
When editing, prune expired hand details but prioritize preserving and refining these long-term strategic takeaways. null only if unchanged and pad is not (empty).
Reply ONLY with JSON: {"card": "<CODE from Legal>", "reasoning": "<short>", "memory": "<rewritten pad, or null only if nothing changed>"}"""

def memory_filename(model: str) -> str:
    """``memory_<bot>.txt``; characters illegal in a file name become ``_``."""
    safe = re.sub(r'[<>:"/\\|?*]', "_", model.strip()) or "bot"
    return f"memory_{safe}.txt"


def read_api_key(path: Path, provider: str = DEFAULT_PROVIDER) -> str:
    """Return the key from the first non-empty line of ``path``."""
    if not path.is_file():
        raise RuntimeError(f"Put the {get_provider(provider).label} API key in {path} (one line).")
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


def response_format_for(level: int, legal_moves: list[str]) -> dict[str, Any] | None:
    """Reply constraint by strictness: 0 = strict schema, 1 = any JSON object, 2 = none.

    On Groq only the gpt-oss models take the strict schema (meta-llama ... take plain JSON mode
    at best); OpenAI chat models take it too. The prompt asks for the same JSON either way and
    ``parse_card`` checks the card against the legal moves.
    """
    if level <= 0:
        return decision_response_format(legal_moves)
    if level == 1:
        return {"type": "json_object"}
    return None


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


def _default_reasoning_effort(provider: str, model: str) -> str | None:
    """``"low"`` for reasoning models, so the token budget is left for the JSON answer."""
    if provider == "groq":
        return "low" if "gpt-oss" in model else None
    return "low" if _OPENAI_REASONING_RE.match(model.strip()) else None


class AIBot(PlayerController):
    """Plays one seat by prompting an LLM (Groq or OpenAI)."""

    def __init__(
        self,
        player_id: str,
        model: str | None = None,
        *,
        provider: str = DEFAULT_PROVIDER,
        temperature: float = 0.0,
        max_tokens: int = DEFAULT_MAX_TOKENS,
        api_key: str | None = None,
        api_key_path: str | Path | None = None,
        exchange_log_path: str | Path | None = None,
        illegal_log_path: str | Path | None = None,
        api_error_log_path: str | Path | None = None,
        memory_path: str | Path | None = None,
        max_memory_chars: int = 600,
        client: Any | None = None,
        guidelines: str | None = None,
        name: str = "",
    ) -> None:
        info = get_provider(provider)
        model = model or info.default_model
        self.player_id = player_id
        self.provider = info.id
        self.model = model
        # Tells two bots of one model apart: it ends up in model_name (so in trajectories.jsonl),
        # in the name of the memory file and in the exchange / illegal-move logs.
        self.name = name.strip()
        self._label = f"{model}_{self.name}" if self.name else model
        # ``None`` (set when the API refuses the value) leaves the parameter out of the request.
        self._temperature: float | None = temperature
        self._max_tokens = max_tokens
        # OpenAI's newer models only take max_completion_tokens; Groq still takes max_tokens.
        self._token_param = "max_completion_tokens" if info.id == "openai" else "max_tokens"
        self._reasoning_effort = _default_reasoning_effort(info.id, model)
        self._api_key = api_key
        self._api_key_path = Path(api_key_path) if api_key_path is not None else info.key_path
        # None means the project log. Tests can point the default at nothing.
        chosen_log = DEFAULT_EXCHANGE_LOG_PATH if exchange_log_path is None else exchange_log_path
        self._exchange_log_path = Path(chosen_log) if chosen_log else None
        chosen_illegal = DEFAULT_ILLEGAL_LOG_PATH if illegal_log_path is None else illegal_log_path
        self._illegal_log_path = Path(chosen_illegal) if chosen_illegal else None
        chosen_api = DEFAULT_API_ERROR_LOG_PATH if api_error_log_path is None else api_error_log_path
        self._api_error_log_path = Path(chosen_api) if chosen_api else None
        # None means logs/memory_<model>.txt (``..._<name>.txt`` for a named bot).
        # "" or False keeps the pad off disk.
        chosen_memory = (
            DEFAULT_MEMORY_DIR / memory_filename(self._label) if memory_path is None else memory_path
        )
        self._memory_path = Path(chosen_memory) if chosen_memory else None
        self._max_memory_chars = max_memory_chars
        # Each model gets its file immediately; notes appear once the model writes them.
        if self._memory_path is not None:
            self._memory_path.parent.mkdir(parents=True, exist_ok=True)
            self._memory_path.touch(exist_ok=True)
        self._client = client
        # How strictly the reply is constrained; relaxed when the API refuses (see ``_create``).
        # Groq takes the strict schema on gpt-oss only; OpenAI chat models take it as a rule.
        self._format_level = 1 if info.id == "groq" and "gpt-oss" not in model else 0
        # None uses USER_GUIDELINES; "" turns the extra instructions off.
        self._guidelines = USER_GUIDELINES if guidelines is None else guidelines

    @property
    def model_name(self) -> str:  # type: ignore[override]
        """Model id (``<model>_<name>`` for a named bot), saved with every logged move."""
        return self._label

    # ------------------------------------------------------------------ API

    def _get_client(self) -> Any:
        """Create the provider's SDK client lazily (needs its package and its key file)."""
        if self._client is None:
            info = get_provider(self.provider)
            key = (
                self._api_key
                if self._api_key is not None
                else read_api_key(self._api_key_path, self.provider)
            )
            try:
                if self.provider == "openai":
                    from openai import OpenAI as Client
                else:
                    from groq import Groq as Client
            except ImportError as exc:  # pragma: no cover - depends on environment
                raise RuntimeError(
                    f"Install the {info.label} SDK: pip install {info.package}"
                ) from exc
            self._client = Client(api_key=key)
        return self._client

    # --------------------------------------------------------------- prompts

    def build_messages(self, observation: PlayerObservation) -> list[dict[str, str]]:
        """System + user messages for the current observation."""
        parts: list[str] = []
        mem = self.read_memory()
        parts.append(f"### Your Memory Pad ({len(mem)}/{self._max_memory_chars} chars)\n{mem}")
        parts.append("### Current state (you are " + observation.player_id + ")")
        parts.append(observation.to_icl_prompt())
        system = SYSTEM_PROMPT + f"\n\nYou are player {self.player_id}."
        extra = self._guidelines.strip()
        if extra:
            system += (
                "\n\nWhen choosing a card, the text below matters most. "
                "Prioritize it over every other guideline.\n"
                + extra
            )
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
            self._token_param: self._max_tokens,
        }
        if self._temperature is not None:
            request["temperature"] = self._temperature
        response_format = response_format_for(self._format_level, legal)
        if response_format is not None:
            request["response_format"] = response_format
        # Reasoning models (gpt-oss, o-series, gpt-5) write a long chain of thought first.
        # "low" leaves room for the JSON answer in content. On Groq the thought stays on
        # message.reasoning.
        if self._reasoning_effort is not None:
            request["reasoning_effort"] = self._reasoning_effort
        try:
            response = self._create(client, request, legal)
            message = response.choices[0].message
            text = reply_text(message)
            self.last_reasoning = decision_reasoning(message, text)
        except Exception as exc:  # network / API / quota errors must not stop the game
            logger.warning("AI request failed (%s); playing first legal move", exc)
            self.last_reasoning = f"request failed: {exc}"
            self._log_exchange(request, None, legal[0], error=str(exc))
            self._log_api_error(exc, legal, legal[0])
            return legal[0]

        memory = _json_memory(text)
        if memory:
            self._write_memory(memory)

        move = parse_card(text, legal)
        if move is None:
            logger.warning("Illegal or unparsable AI reply %r; playing first legal move", text)
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

    def _create(self, client: Any, request: dict[str, Any], legal: list[str]) -> Any:
        """Send ``request``; a 400 about the token limit or the response format is fixed and retried.

        Models differ: meta-llama has no strict JSON schema, some models cap ``max_tokens``,
        OpenAI reasoning models refuse ``temperature`` or ``reasoning_effort``.
        What the API taught us is remembered, so the next move is not refused again.
        """
        for _ in range(5):
            try:
                return client.chat.completions.create(**request)
            except Exception as exc:
                if not self._relax(request, exc, legal):
                    raise
        return client.chat.completions.create(**request)

    def _relax(self, request: dict[str, Any], exc: Exception, legal: list[str]) -> bool:
        """Adapt ``request`` to a model limit named in ``exc``. ``False`` if it is another error."""
        if getattr(exc, "status_code", 400) != 400:
            return False
        message = str(exc)
        lowered = message.lower()
        limit = _TOKEN_LIMIT_RE.search(message)
        if ("max_tokens" in lowered or "max_completion_tokens" in lowered) and limit is not None:
            allowed = int(limit.group(1))
            if 0 < allowed < request[self._token_param]:
                self._max_tokens = request[self._token_param] = allowed
                return True
        if "temperature" in lowered and "temperature" in request:
            del request["temperature"]
            self._temperature = None
            return True
        if "reasoning_effort" in lowered and "reasoning_effort" in request:
            del request["reasoning_effort"]
            self._reasoning_effort = None
            return True
        if self._format_level < 2 and any(marker in lowered for marker in _FORMAT_ERROR_MARKERS):
            self._format_level += 1
            request.pop("response_format", None)
            relaxed = response_format_for(self._format_level, legal)
            if relaxed is not None:
                request["response_format"] = relaxed
            return True
        return False

    def read_memory(self) -> str:
        """Last ``max_memory_chars`` of the scratchpad, or ``(empty)`` if there is no file."""
        if self._memory_path is None or not self._memory_path.is_file():
            return "(empty)"
        text = self._memory_path.read_text(encoding="utf-8")
        if not text.strip():
            return "(empty)"
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

    def _log_api_error(self, exc: Exception, legal_moves: list[str], fallback_move: str) -> None:
        """Append a request the API refused (no reply to judge, unlike the illegal-move log)."""
        if self._api_error_log_path is None:
            return
        record = {
            "player_id": self.player_id,
            "provider": self.provider,
            "model": self.model,
            "name": self.name,
            "status_code": getattr(exc, "status_code", None),
            "error": str(exc),
            "legal_moves": legal_moves,
            "fallback_move": fallback_move,
        }
        try:
            self._api_error_log_path.parent.mkdir(parents=True, exist_ok=True)
            with self._api_error_log_path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(record, ensure_ascii=False) + "\n")
        except OSError as log_exc:
            logger.warning("Could not write AI API-error log (%s)", log_exc)

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
        """Append a reply that was not a legal card (``illegal`` or ``unparsable``)."""
        if self._illegal_log_path is None:
            return
        record = {
            "player_id": self.player_id,
            "provider": self.provider,
            "model": self.model,
            "name": self.name,
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
            logger.warning("Could not write AI illegal-move log (%s)", exc)

    def _log_exchange(
        self,
        request: dict[str, Any],
        message: Any | None,
        chosen_move: str,
        *,
        error: str | None = None,
    ) -> None:
        """Append the prompt sent to the API and the raw reply. Never includes the API key."""
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
            "provider": self.provider,
            "model": request.get("model", self.model),
            "name": self.name,
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
            logger.warning("Could not write AI exchange log (%s)", exc)
