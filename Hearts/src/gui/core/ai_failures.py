"""Recognises AI API failures that the bot hides behind a fallback move.

``AIBot`` catches every API error and plays the first legal card, leaving
``last_reasoning == "request failed: <error>"``. The GUI reads that text to stop
a game that cannot go on (no tokens, no access) instead of letting a bot play blindly.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

FAILURE_PREFIX = "request failed:"  # what AIBot writes into last_reasoning

FailureKind = Literal["tokens", "access", "rate"]

# Daily or monetary limits: waiting a minute does not help.
_TOKEN_MARKERS = (
    "per day", "(tpd)", "(rpd)", "insufficient_quota", "exceeded your current quota",
    "quota", "out of tokens", "no tokens",
    # OpenAI: spending cap, no payment method, or a prepaid balance of zero.
    # "no credits remaining" is a 429, so it must match before the generic rate-limit check.
    "billing_hard_limit", "hard limit", "billing_not_active", "account is not active",
    "no credits",
)  # not "billing": per-minute errors also point to the billing page
# Wrong key / no permission / unknown model: every move would fail the same way.
_ACCESS_MARKERS = (
    "error code: 401", "error code: 403", "error code: 404", "invalid_api_key",
    "model_not_found", "does not exist or you do not have access", "permission",
    "organization_restricted", "model_permission_blocked",
    # OpenAI: wrong key, model closed to the project, organization not verified, banned account.
    "incorrect api key", "does not have access to model", "must be verified",
    "account_deactivated", "unsupported_country_region_territory",
)
# Short-lived limits (per minute): later moves may work again.
_RATE_MARKERS = ("rate limit", "rate_limit", "error code: 429", "per minute", "(tpm)", "(rpm)")


@dataclass(frozen=True)
class AIFailure:
    kind: FailureKind
    message: str  # the API's own text, without the "request failed:" prefix

    @property
    def fatal(self) -> bool:
        return self.kind != "rate"


HEADLINES: dict[str, str] = {
    "tokens": "Skończyły się tokeny API",
    "access": "Brak dostępu do modelu AI",
}
REASONS: dict[str, str] = {
    "tokens": "wyczerpany limit tokenów lub środków (dzienny, miesięczny albo na koncie)",
    "access": "model jest niedostępny dla tego klucza API (zła nazwa modelu, klucz albo uprawnienia)",
}


def classify_failure(reasoning: str | None) -> AIFailure | None:
    """``None`` for a normal move; otherwise what went wrong with the request."""
    text = (reasoning or "").strip()
    if not text.lower().startswith(FAILURE_PREFIX):
        return None
    message = text[len(FAILURE_PREFIX):].strip()
    low = message.lower()
    if any(marker in low for marker in _TOKEN_MARKERS):
        return AIFailure("tokens", message)
    if any(marker in low for marker in _ACCESS_MARKERS):
        return AIFailure("access", message)
    if any(marker in low for marker in _RATE_MARKERS):
        return AIFailure("rate", message)
    return None
