# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Ved Buddaraju

"""Server-Sent Events with stable event ids, so clients can resume with Last-Event-ID."""

from __future__ import annotations

from collections.abc import AsyncIterator

from sse_starlette.sse import EventSourceResponse

from gleanwise.pipeline.runtime import Job, QueryRuntime


def parse_last_event_id(header: str | None, query_after: int | None) -> int:
    for raw in (header, str(query_after) if query_after is not None else None):
        if raw and raw.strip().isdigit():
            return int(raw.strip())
    return 0


def sse_response(rt: QueryRuntime, job: Job, after: int) -> EventSourceResponse:
    async def gen() -> AsyncIterator[dict[str, str | int]]:
        async for ev in rt.subscribe(job, after):
            yield {"id": str(ev.id), "event": ev.name, "data": ev.data}

    return EventSourceResponse(
        gen(),
        ping=15,
        headers={"Cache-Control": "no-cache, no-transform", "X-Accel-Buffering": "no"},
        send_timeout=30,
    )
