# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Ved Buddaraju

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Header, Query, Response
from sse_starlette.sse import EventSourceResponse

from gleanwise.api.deps import Auth, RtDep
from gleanwise.api.sse import parse_last_event_id, sse_response
from gleanwise.models import EventCatalog, OkResponse, QueryAccepted, QueryRequest, QueryStatus

router = APIRouter(tags=["query"], dependencies=[Auth])


@router.post(
    "/query",
    response_model=QueryAccepted,
    status_code=202,
    summary="Start a question",
    description="Returns immediately. Open `stream_url` (Server-Sent Events) to receive the answer. "
    "Re-connect with `Last-Event-ID` to resume without losing events.",
)
async def submit(body: QueryRequest, rt: RtDep) -> QueryAccepted:
    job = await rt.submit(body)
    return QueryAccepted(
        query_id=job.query_id, thread_id=job.thread_id, stream_url=f"/stream/{job.query_id}"
    )


@router.get(
    "/stream/{query_id}",
    response_class=EventSourceResponse,
    summary="Stream a query's events (SSE)",
    responses={
        200: {
            "description": "text/event-stream. See `GET /schema/events` for payload shapes.",
            "content": {"text/event-stream": {}},
        }
    },
)
async def stream(
    query_id: str,
    rt: RtDep,
    last_event_id: Annotated[str | None, Header()] = None,
    after: Annotated[int | None, Query(ge=0)] = None,
) -> EventSourceResponse:
    job = rt.get(query_id)
    return sse_response(rt, job, parse_last_event_id(last_event_id, after))


@router.get("/queries/{query_id}", response_model=QueryStatus, summary="Query status")
async def status(query_id: str, rt: RtDep) -> QueryStatus:
    return rt.get(query_id).snapshot()


@router.post("/queries/{query_id}/cancel", response_model=OkResponse, summary="Stop generating")
async def cancel(query_id: str, rt: RtDep) -> OkResponse:
    rt.get(query_id)  # 404 if unknown
    return OkResponse(ok=rt.cancel(query_id))


@router.get(
    "/schema/events",
    response_model=EventCatalog,
    summary="Documentation of SSE event payloads",
    description="Returns an empty catalog; exists so client generators see every event schema.",
)
async def event_catalog(response: Response) -> EventCatalog:
    response.headers["Cache-Control"] = "public, max-age=3600"
    return EventCatalog()
