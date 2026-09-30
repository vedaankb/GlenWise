# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Ved Buddaraju

from __future__ import annotations

from typing import Annotated, Literal

from fastapi import APIRouter, Query, Response

from gleanwise.api.deps import Auth, SvcDep
from gleanwise.errors import NotFound
from gleanwise.export.render import export_markdown, export_pdf, safe_filename
from gleanwise.models import OkResponse, ThreadDetail, ThreadSummary, ThreadUpdate

router = APIRouter(tags=["threads"], dependencies=[Auth])


@router.get("/threads", response_model=list[ThreadSummary], summary="List conversations")
async def list_threads(
    svc: SvcDep,
    q: Annotated[str | None, Query(max_length=200)] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[ThreadSummary]:
    return await svc.store.list_threads(q, limit, offset)


@router.get("/threads/{thread_id}", response_model=ThreadDetail, summary="Get a conversation")
async def get_thread(thread_id: str, svc: SvcDep) -> ThreadDetail:
    t = await svc.store.get_thread(thread_id)
    if t is None:
        raise NotFound("That conversation no longer exists.")
    return t


@router.patch("/threads/{thread_id}", response_model=OkResponse, summary="Rename or pin")
async def update_thread(thread_id: str, body: ThreadUpdate, svc: SvcDep) -> OkResponse:
    if not await svc.store.update_thread(thread_id, body.title, body.pinned):
        raise NotFound("That conversation no longer exists.")
    return OkResponse()


@router.delete("/threads/{thread_id}", response_model=OkResponse, summary="Delete a conversation")
async def delete_thread(thread_id: str, svc: SvcDep) -> OkResponse:
    if not await svc.store.delete_thread(thread_id):
        raise NotFound("That conversation no longer exists.")
    return OkResponse()


@router.delete(
    "/threads/{thread_id}/messages/{message_id}",
    response_model=OkResponse,
    summary="Delete one answer",
)
async def delete_message(thread_id: str, message_id: str, svc: SvcDep) -> OkResponse:
    if not await svc.store.delete_message(message_id):
        raise NotFound("That message no longer exists.")
    return OkResponse()


@router.get(
    "/threads/{thread_id}/export",
    summary="Export a conversation as Markdown or PDF",
    response_class=Response,
)
async def export_thread(
    thread_id: str, svc: SvcDep, format: Literal["md", "pdf"] = "md"
) -> Response:
    t = await svc.store.get_thread(thread_id)
    if t is None:
        raise NotFound("That conversation no longer exists.")
    name = safe_filename(t.title)
    if format == "pdf":
        data = export_pdf(t)
        return Response(
            data,
            media_type="application/pdf",
            headers={"Content-Disposition": f'attachment; filename="{name}.pdf"'},
        )
    return Response(
        export_markdown(t).encode("utf-8"),
        media_type="text/markdown; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{name}.md"'},
    )
