# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Ved Buddaraju

"""OpenAI-compatible surface: POST /v1/chat/completions and GET /v1/models."""

from __future__ import annotations

import json
import time
import uuid
from collections.abc import AsyncIterator
from typing import Any, Literal

from fastapi import APIRouter
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field

from gleanwise.api.deps import Auth, RtDep, SvcDep
from gleanwise.errors import BadRequest, GleanWiseError
from gleanwise.models import Focus, Mode, QueryRequest, Turn

router = APIRouter(prefix="/v1", tags=["openai"], dependencies=[Auth])

MODEL_IDS = {"gleanwise-quick": Mode.quick, "gleanwise-pro": Mode.pro, "gleanwise-deep": Mode.deep}


class ChatMessage(BaseModel):
    role: Literal["system", "user", "assistant", "developer", "tool"]
    content: str | list[dict[str, Any]] | None = None


class ChatRequest(BaseModel):
    model: str = "gleanwise-quick"
    messages: list[ChatMessage] = Field(min_length=1)
    stream: bool = False
    stream_options: dict[str, Any] | None = None
    max_tokens: int | None = None
    temperature: float | None = None
    user: str | None = None


def _text(content: str | list[dict[str, Any]] | None) -> str:
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    return "\n".join(str(p.get("text", "")) for p in content if p.get("type") in {"text", None})


def _oa_error(exc: GleanWiseError) -> dict[str, Any]:
    kind = "invalid_request_error" if exc.status < 500 and exc.status != 429 else "server_error"
    if exc.status == 429:
        kind = "rate_limit_error"
    if exc.status == 401:
        kind = "authentication_error"
    return {
        "error": {
            "message": exc.message + (f" {exc.hint}" if exc.hint else ""),
            "type": kind,
            "code": exc.code,
            "param": None,
        }
    }


def _request_from(body: ChatRequest) -> QueryRequest:
    mode = MODEL_IDS.get(
        body.model, Mode.quick
    )  # unknown ids → Quick; the LLM comes from server settings
    system = [_text(m.content) for m in body.messages if m.role in {"system", "developer"}]
    convo = [
        m for m in body.messages if m.role in {"user", "assistant"} and _text(m.content).strip()
    ]
    if not convo or convo[-1].role != "user":
        raise BadRequest("The last message must be from the user.")
    history = [Turn(role=m.role, content=_text(m.content)[:20000]) for m in convo[:-1]]  # type: ignore[arg-type]
    return QueryRequest(
        query=_text(convo[-1].content)[:8000],
        mode=mode,
        draft=False,
        focus=Focus.general,
        history=history[-40:],
        persist=False,
        instructions="\n".join(system)[:2000] or None,
    )


@router.get("/models", summary="List model ids")
async def list_models(svc: SvcDep) -> dict[str, Any]:
    now = int(time.time())
    return {
        "object": "list",
        "data": [
            {"id": m, "object": "model", "created": now, "owned_by": "gleanwise"} for m in MODEL_IDS
        ],
    }


@router.post(
    "/chat/completions",
    summary="Chat completion with web search and citations",
    response_model=None,
)
async def chat_completions(body: ChatRequest, rt: RtDep) -> Any:
    try:
        req = _request_from(body)
        job = await rt.submit(req)
    except GleanWiseError as exc:
        return JSONResponse(_oa_error(exc), status_code=exc.status)
    cid, created = f"chatcmpl-{uuid.uuid4().hex[:24]}", int(time.time())

    def chunk(delta: dict[str, Any], finish: str | None = None, **extra: Any) -> str:
        payload = {
            "id": cid,
            "object": "chat.completion.chunk",
            "created": created,
            "model": body.model,
            "choices": [{"index": 0, "delta": delta, "finish_reason": finish}],
            **extra,
        }
        return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"

    if body.stream:
        include_usage = bool((body.stream_options or {}).get("include_usage"))

        async def gen() -> AsyncIterator[str]:
            yield chunk({"role": "assistant", "content": ""})
            try:
                async for ev in rt.subscribe(job, 0):
                    data = json.loads(ev.data)
                    if ev.name == "answer_delta":
                        yield chunk({"content": data["text"]})
                    elif ev.name == "error":
                        yield f"data: {json.dumps(_oa_error_from_payload(data))}\n\n"
                        yield "data: [DONE]\n\n"
                        return
                    elif ev.name == "done":
                        cites = data.get("citations", [])
                        extra: dict[str, Any] = {"citations": [c["url"] for c in cites]}
                        yield chunk({}, "stop", **extra)
                        if include_usage:
                            u = data.get("usage", {})
                            pt, ct = u.get("prompt_tokens", 0), u.get("completion_tokens", 0)
                            yield f"data: {json.dumps({'id': cid, 'object': 'chat.completion.chunk', 'created': created, 'model': body.model, 'choices': [], 'usage': {'prompt_tokens': pt, 'completion_tokens': ct, 'total_tokens': pt + ct}})}\n\n"
                yield "data: [DONE]\n\n"
            finally:
                if not job.finished:
                    rt.cancel(job.query_id)  # client went away mid-stream

        return StreamingResponse(
            gen(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    final = await _await_job(rt, job)
    if "code" in final and "answer" not in final:
        return JSONResponse(_oa_error_from_payload(final), status_code=_status_for(final))
    u = final.get("usage", {})
    pt, ct = u.get("prompt_tokens", 0), u.get("completion_tokens", 0)
    return {
        "id": cid,
        "object": "chat.completion",
        "created": created,
        "model": body.model,
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": final.get("answer", "")},
                "finish_reason": "stop",
            }
        ],
        "usage": {"prompt_tokens": pt, "completion_tokens": ct, "total_tokens": pt + ct},
        "citations": [c["url"] for c in final.get("citations", [])],
        "sources": [
            {"id": s["id"], "url": s["url"], "title": s["title"]}
            for s in final.get("sources", [])
            if s.get("used_in_answer")
        ],
    }


async def _await_job(rt: RtDep, job: Any) -> dict[str, Any]:
    try:
        return await job.wait()
    except BaseException:
        rt.cancel(job.query_id)
        raise


def _oa_error_from_payload(p: dict[str, Any]) -> dict[str, Any]:
    return {
        "error": {
            "message": p.get("message", "Error") + (f" {p['hint']}" if p.get("hint") else ""),
            "type": "server_error",
            "code": p.get("code"),
            "param": None,
        }
    }


def _status_for(p: dict[str, Any]) -> int:
    return {
        "llm_not_configured": 424,
        "llm_auth": 401,
        "llm_rate_limit": 429,
        "deadline_exceeded": 504,
        "busy": 429,
    }.get(str(p.get("code")), 502)
