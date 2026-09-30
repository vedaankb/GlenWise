# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Ved Buddaraju

"""LiteLLM wrapper: typed errors, timeouts, first-token deadline, usage accounting, JSON helpers."""

from __future__ import annotations

import asyncio
import json
import logging
import re
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any, Literal

from gleanwise.config import Settings
from gleanwise.egress.log import LOG
from gleanwise.egress.policy import (
    assert_strict_local_llm,
    hostname_of,
    is_local_llm_endpoint,
    redact_pii,
    restore_pii,
)
from gleanwise.errors import GleanWiseError, LLMError, LLMNotConfigured, classify_llm_exception
from gleanwise.util.text import approx_tokens

log = logging.getLogger(__name__)


@dataclass
class Usage:
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cost_usd: float | None = None
    calls: int = 0
    _cost_known: bool = field(default=False, repr=False)

    def add(self, model: str, prompt: int, completion: int) -> None:
        self.prompt_tokens += prompt
        self.completion_tokens += completion
        self.calls += 1
        try:
            import litellm

            p, c = litellm.cost_per_token(
                model=model, prompt_tokens=prompt, completion_tokens=completion
            )
            self.cost_usd = (self.cost_usd or 0.0) + float(p) + float(c)
            self._cost_known = True
        except Exception:
            pass  # unknown / local models have no price → leave cost as-is (None when never priced)


@dataclass
class Delta:
    kind: Literal["text", "reasoning"]
    text: str


class LLM:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def model_for(self, override: str | None) -> str:
        model = (override or self.settings.llm_model or "").strip()
        if not model:
            raise LLMNotConfigured(
                "No language model is configured yet.",
                hint="Open Settings and choose a model (for example a local Ollama model or a hosted API key).",
            )
        if self.settings.strict_local:
            assert_strict_local_llm(model, self.settings.llm_api_base, self.settings.local_hosts)
        return model

    def is_cloud(self, model: str | None = None) -> bool:
        m = model or self.settings.llm_model
        return not is_local_llm_endpoint(m, self.settings.llm_api_base, self.settings.local_hosts)

    def prepare_messages(
        self, messages: list[dict[str, str]]
    ) -> tuple[list[dict[str, str]], dict[str, str]]:
        """Optionally redact PII before a cloud call; return (messages, restore_map)."""
        if not (self.settings.redact_pii and self.is_cloud()):
            return messages, {}
        mapping: dict[str, str] = {}
        out: list[dict[str, str]] = []
        for msg in messages:
            text, m = redact_pii(msg.get("content") or "")
            mapping.update(m)
            out.append({**msg, "content": text})
        return out, mapping

    def _log_call(self, model: str) -> None:
        host = hostname_of(self.settings.llm_api_base) or hostname_of(
            model.split("/")[0] + ".local"
        )
        if self.settings.llm_api_base:
            host = hostname_of(self.settings.llm_api_base) or host
        from urllib.parse import urlsplit

        port = 443
        if self.settings.llm_api_base:
            parts = urlsplit(self.settings.llm_api_base)
            port = parts.port or (443 if parts.scheme == "https" else 80)
        LOG.record(host or "llm", port, purpose="llm", status="ok")

    def _kwargs(self, timeout: float) -> dict[str, Any]:
        kw: dict[str, Any] = {"timeout": timeout, "num_retries": 1, "drop_params": True}
        if self.settings.llm_api_key:
            kw["api_key"] = self.settings.llm_api_key
        if self.settings.llm_api_base:
            kw["api_base"] = self.settings.llm_api_base
            # Self-hosted OpenAI-compatible servers (LM Studio, vLLM, Ollama) usually need no key, but the
            # OpenAI client refuses to start without one.
            kw.setdefault("api_key", "not-needed")
        return kw

    def _err(self, exc: BaseException, model: str) -> GleanWiseError:
        return classify_llm_exception(exc, model=model, base=self.settings.llm_api_base)

    async def complete(
        self,
        messages: list[dict[str, str]],
        *,
        model: str | None = None,
        usage: Usage | None = None,
        max_tokens: int = 600,
        temperature: float = 0.2,
        timeout: float | None = None,
    ) -> str:
        import litellm

        m = self.model_for(model)
        messages, restore = self.prepare_messages(messages)
        self._log_call(m)
        try:
            resp = await litellm.acompletion(
                model=m,
                messages=messages,
                max_tokens=max_tokens,
                temperature=temperature,
                **self._kwargs(timeout or 40.0),
            )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            raise self._err(exc, m) from exc
        text = (resp.choices[0].message.content or "").strip()
        if usage is not None:
            u = getattr(resp, "usage", None)
            usage.add(
                m,
                int(
                    getattr(u, "prompt_tokens", 0)
                    or sum(approx_tokens(x["content"]) for x in messages)
                ),
                int(getattr(u, "completion_tokens", 0) or approx_tokens(text)),
            )
        return restore_pii(text, restore) if restore else text

    async def stream(  # noqa: C901
        self,
        messages: list[dict[str, str]],
        *,
        model: str | None = None,
        usage: Usage | None = None,
        max_tokens: int = 2200,
        temperature: float = 0.3,
    ) -> AsyncIterator[Delta]:
        import litellm

        m = self.model_for(model)
        messages, restore_map = self.prepare_messages(messages)
        self._log_call(m)
        try:
            stream = await litellm.acompletion(
                model=m,
                messages=messages,
                stream=True,
                max_tokens=max_tokens,
                temperature=temperature,
                stream_options={"include_usage": True},
                **self._kwargs(self.settings.llm_timeout_s),
            )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            raise self._err(exc, m) from exc

        out_chars = 0
        final_usage: Any = None
        it = stream.__aiter__()
        first = True
        try:
            while True:
                try:
                    if first:
                        chunk = await asyncio.wait_for(
                            it.__anext__(), self.settings.llm_first_token_timeout_s
                        )
                    else:
                        chunk = await asyncio.wait_for(it.__anext__(), self.settings.llm_timeout_s)
                except StopAsyncIteration:
                    break
                except TimeoutError as exc:
                    raise LLMError(
                        "The model stopped responding.",
                        hint="It may be overloaded or still loading. Retry, or try a smaller/faster model.",
                    ) from exc
                first = False
                if getattr(chunk, "usage", None):
                    final_usage = chunk.usage
                if not chunk.choices:
                    continue
                delta = chunk.choices[0].delta
                reasoning = getattr(delta, "reasoning_content", None)
                if reasoning:
                    yield Delta(
                        "reasoning",
                        restore_pii(reasoning, restore_map) if restore_map else reasoning,
                    )
                content = getattr(delta, "content", None)
                if content:
                    out_chars += len(content)
                    yield Delta(
                        "text", restore_pii(content, restore_map) if restore_map else content
                    )
        except asyncio.CancelledError:
            raise
        except GleanWiseError:
            raise
        except Exception as exc:
            raise self._err(exc, m) from exc
        finally:
            aclose = getattr(stream, "aclose", None)
            if aclose is not None:
                try:
                    await aclose()
                except Exception:
                    pass
            if usage is not None:
                pt = int(
                    getattr(final_usage, "prompt_tokens", 0)
                    or sum(approx_tokens(x["content"]) for x in messages)
                )
                ct = int(getattr(final_usage, "completion_tokens", 0) or max(1, out_chars // 4))
                usage.add(m, pt, ct)

    # -- JSON helper ----------------------------------------------------------------------
    async def complete_json(
        self,
        messages: list[dict[str, str]],
        *,
        model: str | None = None,
        usage: Usage | None = None,
        max_tokens: int = 500,
        timeout: float = 30.0,
    ) -> dict[str, Any]:
        raw = await self.complete(
            messages,
            model=model,
            usage=usage,
            max_tokens=max_tokens,
            temperature=0.1,
            timeout=timeout,
        )
        return parse_json_object(raw)


def parse_json_object(raw: str) -> dict[str, Any]:
    """Extract the first JSON object from a model reply (tolerates fences and chatter)."""
    raw = raw.strip()
    raw = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw, flags=re.I)
    try:
        data = json.loads(raw)
        return data if isinstance(data, dict) else {}
    except json.JSONDecodeError:
        pass
    start = raw.find("{")
    while start != -1:
        depth = 0
        for i in range(start, len(raw)):
            depth += raw[i] == "{"
            depth -= raw[i] == "}"
            if depth == 0:
                try:
                    data = json.loads(raw[start : i + 1])
                    return data if isinstance(data, dict) else {}
                except json.JSONDecodeError:
                    break
        start = raw.find("{", start + 1)
    return {}
