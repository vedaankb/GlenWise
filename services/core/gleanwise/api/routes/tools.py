# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Ved Buddaraju

"""Stateless building blocks for integrations (MCP, scripts): search, fetch, retrieve, favicons."""

from __future__ import annotations

import asyncio
import hashlib
import re
from collections import OrderedDict
from typing import Annotated

from fastapi import APIRouter, Query, Response

from gleanwise.api.deps import Auth, SvcDep
from gleanwise.chunk.segment import chunk_document
from gleanwise.errors import BadRequest, GleanWiseError, NoResults, NotFound
from gleanwise.models import (
    FetchRequest,
    FetchResponse,
    RetrievedChunk,
    RetrieveRequest,
    RetrieveResponse,
    SearchRequest,
    SearchResponse,
)
from gleanwise.retrieve.hybrid import retrieve
from gleanwise.util.text import canonicalize_url, truncate

router = APIRouter(tags=["tools"])
_DOMAIN = re.compile(r"^(?=.{1,253}$)([a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$", re.I)
_FAV_CACHE: OrderedDict[str, tuple[bytes, str]] = OrderedDict()
_PALETTE = ("#4f46e5", "#0891b2", "#059669", "#d97706", "#dc2626", "#7c3aed", "#db2777", "#475569")


@router.post(
    "/search", response_model=SearchResponse, dependencies=[Auth], summary="Web search (no LLM)"
)
async def search(body: SearchRequest, svc: SvcDep) -> SearchResponse:
    try:
        out = await svc.search.search(
            body.query, focus=body.focus, limit=body.limit, locale=body.locale
        )
    except NoResults as exc:
        return SearchResponse(
            query=body.query, results=[], warnings=[exc.message, *([exc.hint] if exc.hint else [])]
        )
    return SearchResponse(query=body.query, results=out.results, warnings=out.warnings)


@router.post(
    "/fetch", response_model=FetchResponse, dependencies=[Auth], summary="Fetch and clean one page"
)
async def fetch_page(body: FetchRequest, svc: SvcDep) -> FetchResponse:
    page = await svc.fetcher.fetch(body.url)
    text = page.doc.text
    return FetchResponse(
        url=body.url,
        final_url=page.final_url,
        title=page.doc.title,
        text=truncate(text, body.max_chars),
        truncated=len(text) > body.max_chars or page.truncated,
        from_cache=page.from_cache,
    )


@router.post(
    "/retrieve",
    response_model=RetrieveResponse,
    dependencies=[Auth],
    summary="Passages from the local index",
)
async def retrieve_passages(body: RetrieveRequest, svc: SvcDep) -> RetrieveResponse:
    doc_ids: list[str] | None = None
    if body.urls:
        if len(body.urls) > 10:
            raise BadRequest("At most 10 URLs per request.")
        doc_ids = []

        async def ingest(u: str) -> None:
            try:
                page = await svc.fetcher.fetch(u)
            except GleanWiseError:
                return
            d = page.doc
            if not (page.from_cache and await svc.store.chunk_count(d.id)):
                chunks = await asyncio.to_thread(
                    chunk_document,
                    d.text,
                    url=d.url,
                    doc_id=d.id,
                    max_tokens=svc.settings.chunk_tokens,
                    overlap_tokens=svc.settings.chunk_overlap_tokens,
                )
                await svc.store.replace_chunks(d.id, chunks)
            doc_ids.append(d.id)

        await asyncio.gather(*[ingest(u) for u in body.urls])
    res = await retrieve(
        store=svc.store,
        embedder=svc.embedder,
        reranker=svc.reranker,
        queries=[body.query],
        doc_ids=doc_ids,
        k=body.limit,
    )
    docs = await svc.store.get_documents(sorted({c.doc_id for c in res.chunks}))
    return RetrieveResponse(
        query=body.query,
        chunks=[
            RetrievedChunk(
                chunk_id=c.id,
                url=c.url,
                title=docs[c.doc_id].title if c.doc_id in docs else "",
                heading_path=c.heading_path,
                text=c.text,
                score=float(c.score or 0.0),
            )
            for c in res.chunks
        ],
    )


def _letter_icon(domain: str) -> tuple[bytes, str]:
    letter = (domain[:1] or "?").upper()
    color = _PALETTE[
        int(hashlib.md5(domain.encode(), usedforsecurity=False).hexdigest(), 16) % len(_PALETTE)
    ]
    svg = (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32"><rect width="32" height="32" rx="8" fill="{color}"/>'
        f'<text x="16" y="22" font-family="system-ui,sans-serif" font-size="17" font-weight="600" text-anchor="middle" fill="#fff">{letter}</text></svg>'
    )
    return svg.encode(), "image/svg+xml"


@router.get(
    "/proxy/favicon",
    summary="Privacy-preserving favicon (fetched server-side)",
    response_class=Response,
)
async def favicon(svc: SvcDep, domain: Annotated[str, Query(max_length=253)]) -> Response:
    domain = domain.lower().strip()
    if not _DOMAIN.match(domain):
        raise BadRequest("Invalid domain.")
    hit = _FAV_CACHE.get(domain)
    if hit is None:
        hit = _letter_icon(domain)
        try:
            res = await svc.http.get(
                f"https://{domain}/favicon.ico",
                max_bytes=100_000,
                timeout=4.0,
                max_redirects=2,
                accept_types=("image/",),
            )
            ctype = res.content_type
            if res.status == 200 and res.body and ctype.startswith("image/") and "svg" not in ctype:
                hit = (res.body, ctype)
        except GleanWiseError:
            pass
        _FAV_CACHE[domain] = hit
        while len(_FAV_CACHE) > 512:
            _FAV_CACHE.popitem(last=False)
    body, ctype = hit
    return Response(
        body,
        media_type=ctype,
        headers={
            "Cache-Control": "public, max-age=86400",
            "Content-Security-Policy": "sandbox; default-src 'none'; style-src 'unsafe-inline'",
        },
    )


_IMG_CACHE: OrderedDict[str, tuple[bytes, str]] = OrderedDict()
_IMG_MAX_BYTES = 5_000_000
_SAFE_IMAGE_TYPES = ("image/png", "image/jpeg", "image/gif", "image/webp", "image/avif")


@router.get(
    "/proxy/image",
    dependencies=[Auth],
    summary="Fetch a remote image server-side so the browser never contacts the origin",
    response_class=Response,
)
async def proxy_image(svc: SvcDep, url: Annotated[str, Query(max_length=2048)]) -> Response:
    """Answers can embed images, and a prompt-injected page could point one at an attacker's server
    to leak data in the URL. Routing every image through here (SSRF-guarded, raster types only,
    size-capped) removes both the tracking and the exfiltration channel."""
    key = canonicalize_url(url)
    hit = _IMG_CACHE.get(key)
    if hit is None:
        res = await svc.http.get(
            url, max_bytes=_IMG_MAX_BYTES, timeout=8.0, max_redirects=3, accept_types=("image/",)
        )
        ctype = res.content_type.split(";")[0].strip().lower()
        if res.status != 200 or not res.body:
            raise NotFound("That image could not be loaded.")
        if ctype not in _SAFE_IMAGE_TYPES:  # SVG can carry script; anything else isn't an image
            raise BadRequest("Only PNG, JPEG, GIF, WebP and AVIF images can be shown.")
        hit = (res.body, ctype)
        _IMG_CACHE[key] = hit
        while len(_IMG_CACHE) > 64:
            _IMG_CACHE.popitem(last=False)
    body, ctype = hit
    return Response(
        body,
        media_type=ctype,
        headers={
            "Cache-Control": "private, max-age=3600",
            "X-Content-Type-Options": "nosniff",
            "Content-Security-Policy": "sandbox; default-src 'none'",
            "Cross-Origin-Resource-Policy": "same-origin",
        },
    )


__all__ = ["canonicalize_url", "router"]
