# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Ved Buddaraju

"""Executes one query end-to-end: run mode → persist → telemetry → terminal event."""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
import time
from typing import TYPE_CHECKING, Any

import httpx

from gleanwise.egress.policy import is_local_llm_endpoint
from gleanwise.errors import DeadlineExceeded, GleanWiseError
from gleanwise.models import DataFlowInfo, DoneEvent, Mode, UsageInfo
from gleanwise.pipeline.context import RunContext
from gleanwise.pipeline.modes import RUNNERS, Answer
from gleanwise.telemetry import metrics
from gleanwise.telemetry.logging import query_id_var

if TYPE_CHECKING:
    from gleanwise.pipeline.runtime import Job, QueryRuntime

log = logging.getLogger(__name__)


async def execute(rt: QueryRuntime, job: Job) -> None:  # noqa: C901
    svc = rt.svc
    req = job.request
    query_id_var.set(job.query_id)
    status = "error"
    error_code: str | None = None
    ctx: RunContext | None = None
    acquired = False
    try:
        await rt.acquire(job)
        acquired = True
        # Private threads (D6): never persist, never write cache/traces/webhooks.
        if req.private:
            req = req.model_copy(update={"persist": False})
            job.request = req
        history = list(req.history or []) if req.history is not None else []
        if req.history is None and req.persist and req.thread_id:
            history = await svc.store.history(job.thread_id, 6)
            if (
                req.regenerate_message_id
            ):  # don't let the answer being replaced influence the new one
                history = history[:-2]
        model = svc.llm.model_for(req.model)
        ctx = RunContext(
            svc=svc,
            req=req,
            query_id=job.query_id,
            thread_id=job.thread_id,
            history=history,
            emit=job.emit,
            model=model,
            deadline_s=svc.settings.deadline_for(req.mode.value),
        )
        try:
            async with asyncio.timeout(ctx.deadline_s):
                answer: Answer = await RUNNERS[req.mode](ctx)
        except TimeoutError as exc:
            if ctx.time_left() > 1:  # a library-level timeout, not our deadline
                raise
            raise DeadlineExceeded(
                f"This {req.mode.value} search ran past its {int(ctx.deadline_s)}s limit.",
                hint="Try Quick mode, or ask a narrower question.",
            ) from exc

        message_id: str | None = None
        if req.persist:
            if req.regenerate_message_id:
                await svc.store.delete_message(req.regenerate_message_id)
            msg = await svc.store.add_turn(
                job.thread_id,
                {
                    "role": "user",
                    "content": req.query,
                    "mode": req.mode.value,
                    "focus": req.focus.value,
                },
                {
                    "role": "assistant",
                    "content": answer.text,
                    "mode": req.mode.value,
                    "focus": req.focus.value,
                    "citations": [c.model_dump() for c in answer.citations],
                    "sources": [s.model_dump() for s in ctx.sources.values()],
                    "query_id": job.query_id,
                    "follow_ups": answer.follow_ups,
                    "research_summary": answer.research_summary,
                    "research_log": answer.research_log,
                },
            )
            message_id = msg.id
        job.status = "complete"
        pages = 0
        if ctx:
            for src in ctx.sources.values():
                if src.state in {"read", "reading"}:
                    pages += 1
        flow = DataFlowInfo(
            search=True,
            pages_fetched=pages,
            model=ctx.model if ctx else "",
            model_local=is_local_llm_endpoint(
                ctx.model if ctx else "", svc.settings.llm_api_base, svc.settings.local_hosts
            ),
            redaction=bool(svc.settings.redact_pii)
            and not is_local_llm_endpoint(
                ctx.model if ctx else "", svc.settings.llm_api_base, svc.settings.local_hosts
            ),
            private=bool(req.private),
            proxy=bool(svc.settings.egress_gateway),
            socks5=bool(svc.settings.socks5_url)
            and (svc.settings.socks5_for_search or svc.settings.socks5_for_fetch),
            strict_local=bool(svc.settings.strict_local),
        )
        job.emit(
            "done",
            DoneEvent(
                query_id=job.query_id,
                thread_id=job.thread_id,
                message_id=message_id,
                status="complete",
                answer=answer.text,
                citations=answer.citations,
                sources=list(ctx.sources.values()),
                follow_ups=answer.follow_ups,
                usage=_usage(ctx),
                duration_ms=_ms(ctx),
                research_summary=answer.research_summary,
                data_flow=flow,
            ),
        )
        status = "complete"
    except asyncio.CancelledError:
        if not job.cancel_requested:
            job.status = "cancelled"
            job.emit(
                "error",
                {"code": "shutdown", "message": "The server is shutting down.", "retryable": True},
            )
            raise
        status = "cancelled"
        job.status = "cancelled"
        job.emit(
            "done",
            DoneEvent(
                query_id=job.query_id,
                thread_id=job.thread_id,
                status="cancelled",
                sources=list(ctx.sources.values()) if ctx else [],
                usage=_usage(ctx) if ctx else UsageInfo(),
                duration_ms=_ms(ctx) if ctx else 0,
            ),
        )
    except GleanWiseError as exc:
        error_code = exc.code
        job.status = "error"
        if exc.detail:
            log.info("query failed: %s (%s) detail=%s", exc.code, exc.message, exc.detail)
        job.emit("error", exc.to_payload())
    except Exception:
        error_code = "internal"
        job.status = "error"
        log.exception("unhandled error in query")
        job.emit(
            "error",
            {
                "code": "internal",
                "message": "Something went wrong on our side.",
                "hint": f"Reference {job.query_id[:8]} when reporting this.",
                "action": "retry",
                "retryable": True,
            },
        )
    finally:
        if acquired:
            rt.release()
        if not job.finished:  # belt and braces: a stream must always terminate
            job.emit(
                "error",
                {"code": "internal", "message": "The query ended unexpectedly.", "retryable": True},
            )
        await _finalize(rt, job, ctx, status, error_code)


def _ms(ctx: RunContext) -> int:
    return int((time.monotonic() - ctx.started) * 1000)


def _usage(ctx: RunContext) -> UsageInfo:
    u = ctx.usage
    return UsageInfo(
        prompt_tokens=u.prompt_tokens, completion_tokens=u.completion_tokens, cost_usd=u.cost_usd
    )


async def _finalize(
    rt: QueryRuntime, job: Job, ctx: RunContext | None, status: str, error_code: str | None
) -> None:
    svc = rt.svc
    mode: Mode = job.request.mode
    metrics.QUERIES.labels(mode.value, status if not error_code else error_code).inc()
    trace: dict[str, Any] = {
        "query_id": job.query_id,
        "thread_id": job.thread_id,
        "mode": mode.value,
        "focus": job.request.focus.value,
        "status": status,
        "error_code": error_code,
        "query_len": len(job.request.query),
        "query_sha": hashlib.sha256(job.request.query.encode()).hexdigest()[
            :16
        ],  # never the raw text
    }
    if ctx is not None:
        u = ctx.usage
        metrics.TOKENS.labels("prompt").inc(u.prompt_tokens)
        metrics.TOKENS.labels("completion").inc(u.completion_tokens)
        if u.cost_usd:
            metrics.COST.inc(u.cost_usd)
        trace.update(
            model=ctx.model,
            duration_ms=_ms(ctx),
            ttft_ms=int((ctx.first_token_at - ctx.started) * 1000) if ctx.first_token_at else None,
            stages=ctx.stages,
            sources=len(ctx.sources),
            warnings=sorted(ctx.warned),
            usage={
                "prompt_tokens": u.prompt_tokens,
                "completion_tokens": u.completion_tokens,
                "cost_usd": u.cost_usd,
                "calls": u.calls,
            },
        )
    try:
        if not job.request.private:
            await svc.store.add_trace(
                job.query_id, job.thread_id if job.request.persist else None, trace
            )
    except Exception as exc:
        log.warning("could not persist trace: %r", exc)
    if (
        svc.settings.webhook_url
        and svc.settings.operator_webhooks
        and not job.request.private
        and status in {"complete", "error"}
    ):
        svc.spawn(
            deliver_webhook(svc.settings.webhook_url, svc.settings.webhook_secret, trace),
            f"webhook-{job.query_id[:8]}",
        )


async def deliver_webhook(url: str, secret: str, payload: dict[str, Any]) -> None:
    """POST a signed completion event with bounded retries. Never includes answer text."""
    body = json.dumps({"event": "query.finished", **payload}, default=str).encode()
    headers = {"Content-Type": "application/json", "User-Agent": "GleanWise-Webhook/1"}
    if secret:
        headers["X-GleanWise-Signature"] = (
            "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
        )
    async with httpx.AsyncClient(timeout=8.0, trust_env=False) as client:
        for attempt in range(4):
            try:
                r = await client.post(url, content=body, headers=headers)
                if r.status_code < 500 and r.status_code != 429:
                    return
            except httpx.HTTPError:
                pass
            await asyncio.sleep(2**attempt)
    log.warning("webhook delivery to %s failed after retries", url)
