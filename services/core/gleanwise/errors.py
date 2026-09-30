# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Ved Buddaraju

"""Typed, actionable errors.

Every failure a user can see carries a stable ``code``, a human ``message``, an optional ``hint``
telling them what to do, and an ``action`` the UI can turn into a button.
"""

from __future__ import annotations

from typing import Any, Literal

Action = Literal["open_settings", "retry", "open_diagnostics", "shorten_query"]


class GleanWiseError(Exception):
    code = "internal"
    status = 500
    retryable = False
    action: Action | None = None

    def __init__(
        self,
        message: str,
        *,
        hint: str | None = None,
        action: Action | None = None,
        detail: str | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.hint = hint
        if action is not None:
            self.action = action
        self.detail = detail

    def to_payload(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "message": self.message,
            "hint": self.hint,
            "action": self.action,
            "retryable": self.retryable,
        }


class LLMNotConfigured(GleanWiseError):
    code = "llm_not_configured"
    status = 424
    action = "open_settings"


class LLMAuthError(GleanWiseError):
    code = "llm_auth"
    status = 401
    action = "open_settings"


class LLMRateLimited(GleanWiseError):
    code = "llm_rate_limit"
    status = 429
    retryable = True
    action = "retry"


class LLMUnreachable(GleanWiseError):
    code = "llm_unreachable"
    status = 502
    retryable = True
    action = "open_diagnostics"


class LLMBadModel(GleanWiseError):
    code = "llm_model_not_found"
    status = 404
    action = "open_settings"


class LLMError(GleanWiseError):
    code = "llm_error"
    status = 502
    retryable = True
    action = "retry"


class SearchUnavailable(GleanWiseError):
    code = "search_unavailable"
    status = 503
    retryable = True
    action = "open_diagnostics"


class NoResults(GleanWiseError):
    code = "search_no_results"
    status = 404
    action = None


class FetchBlocked(GleanWiseError):
    code = "fetch_blocked"
    status = 403


class FetchFailed(GleanWiseError):
    code = "fetch_failed"
    status = 502
    retryable = True


class Busy(GleanWiseError):
    code = "busy"
    status = 429
    retryable = True
    action = "retry"


class DeadlineExceeded(GleanWiseError):
    code = "deadline_exceeded"
    status = 504
    retryable = True
    action = "retry"


class BadRequest(GleanWiseError):
    code = "bad_request"
    status = 422


class NotFound(GleanWiseError):
    code = "not_found"
    status = 404


class Conflict(GleanWiseError):
    code = "conflict"
    status = 409


class Unauthorized(GleanWiseError):
    code = "unauthorized"
    status = 401


def classify_llm_exception(
    exc: BaseException, *, model: str = "", base: str = ""
) -> GleanWiseError:
    """Map provider/LiteLLM exceptions onto actionable GleanWiseErrors."""
    if isinstance(exc, GleanWiseError):
        return exc
    name = type(exc).__name__
    text = str(exc)
    low = text.lower()
    where = f" at {base}" if base else ""
    if "api_key" in low and ("must be set" in low or "not set" in low or "missing" in low):
        return LLMAuthError(
            "No API key is set for this model.",
            hint="Add the key in Settings. Local servers that need no key can use any placeholder value.",
            detail=text[:300],
        )
    if name == "AuthenticationError" or "invalid api key" in low or "incorrect api key" in low:
        return LLMAuthError(
            "The model provider rejected your API key.",
            hint="Open Settings and re-enter the key for this provider.",
            detail=text[:300],
        )
    if name == "RateLimitError" or "rate limit" in low or "quota" in low:
        return LLMRateLimited(
            "The model provider is rate-limiting this key.",
            hint="Wait a few seconds and retry, or switch to another model.",
            detail=text[:300],
        )
    if name == "NotFoundError" or "model_not_found" in low or "does not exist" in low:
        return LLMBadModel(
            f"The model '{model}' was not found{where}.",
            hint="Check the model name in Settings (for Ollama, run `ollama pull <model>` first).",
            detail=text[:300],
        )
    if name in {"APIConnectionError", "ServiceUnavailableError", "Timeout", "APITimeoutError"} or (
        "connection" in low and ("refused" in low or "error" in low)
    ):
        return LLMUnreachable(
            f"Could not reach the model server{where}.",
            hint="Is it running? Local servers such as Ollama must be started first.",
            detail=text[:300],
        )
    if name == "BadRequestError" and ("context" in low and "length" in low):
        return LLMError(
            "The question plus sources exceed the model's context window.",
            hint="Use Quick mode, or pick a model with a larger context.",
            detail=text[:300],
        )
    return LLMError(
        "The model provider returned an error.",
        hint="Check the model name and server address in Settings; Diagnostics shows the provider's message.",
        detail=text[:300],
    )


class Forbidden(GleanWiseError):
    code = "forbidden"
    status = 403
