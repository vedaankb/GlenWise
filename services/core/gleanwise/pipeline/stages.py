# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Ved Buddaraju

"""Reusable pipeline stages. Modes (quick/pro/deep) are compositions of these."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass

from gleanwise.chunk.segment import chunk_document
from gleanwise.errors import GleanWiseError
from gleanwise.llm import prompts
from gleanwise.llm.citations import finalize_answer
from gleanwise.models import (
    AnswerCompleteEvent,
    AnswerDeltaEvent,
    Chunk,
    Citation,
    FollowUpsEvent,
    ReasoningDeltaEvent,
    Source,
    SourcesEvent,
    SourceUpdateEvent,
    VisitEvent,
)
from gleanwise.pipeline.context import RunContext
from gleanwise.retrieve.hybrid import RetrievalResult, retrieve
from gleanwise.search.client import SearchOutcome
from gleanwise.telemetry import metrics
from gleanwise.util.text import canonicalize_url, truncate

log = logging.getLogger(__name__)

CONTEXT_BUDGET_CHARS = {"quick": 14_000, "pro": 30_000, "deep": 60_000}


# --- query understanding ------------------------------------------------------------------------
async def rewrite_query(ctx: RunContext) -> str:
    q = ctx.req.query.strip()
    if not ctx.history:
        return q
    async with ctx.stage("rewrite"):
        try:
            out = await ctx.svc.llm.complete(
                prompts.rewrite_messages(ctx.history, q),
                model=ctx.model,
                usage=ctx.usage,
                max_tokens=80,
                timeout=15,
            )
        except GleanWiseError as exc:
            if exc.code in {"llm_not_configured", "llm_auth"}:
                raise
            return q
    line = out.strip().splitlines()[0].strip(" \"'") if out.strip() else ""
    return line[:300] or q


async def make_plan(ctx: RunContext, query: str, n: int) -> list[str]:
    queries = [query]
    async with ctx.stage("plan", n=n):
        try:
            data = await ctx.svc.llm.complete_json(
                prompts.plan_messages(query, n=n, focus=ctx.req.focus.value),
                model=ctx.model,
                usage=ctx.usage,
            )
        except GleanWiseError as exc:
            if exc.code in {"llm_not_configured", "llm_auth"}:
                raise
            data = {}
    raw = data.get("queries")
    if isinstance(raw, list):
        seen = {query.lower()}
        for item in raw:
            if (
                isinstance(item, str)
                and (s := item.strip())
                and s.lower() not in seen
                and len(s) < 300
            ):
                seen.add(s.lower())
                queries.append(s)
    return queries[: n + 1] if n > 1 else queries[:1]


# --- search ----------------------------------------------------------------------------------------
async def search_stage(
    ctx: RunContext, queries: list[str], *, per_query: int, total: int
) -> list[Source]:
    """Run all queries, interleave results by rank, dedupe, register, and announce new sources."""
    async with ctx.stage("search", queries=len(queries)) as rec:
        results = await asyncio.gather(
            *[
                ctx.svc.search.search(q, focus=ctx.req.focus, limit=per_query, locale=ctx.locale)
                for q in queries
            ],
            return_exceptions=True,
        )
        ok = [r for r in results if isinstance(r, SearchOutcome)]
        if not ok:
            errors = [r for r in results if isinstance(r, BaseException)]
            cancelled = [e for e in errors if isinstance(e, asyncio.CancelledError)]
            if cancelled:
                raise cancelled[0]
            raise errors[0]
        for r in ok:
            for w in r.warnings:
                ctx.warn("search_engine", w)
        merged: list[Source] = []
        depth = max(len(r.results) for r in ok)
        for i in range(depth):
            for r in ok:
                if i < len(r.results):
                    merged.append(r.results[i])
        seen_now: set[str] = set()
        unique: list[Source] = []
        for src in merged:  # interleaved order, dedupe across the queries' result lists
            key = canonicalize_url(src.url)
            if key not in seen_now:
                seen_now.add(key)
                unique.append(src)
        fresh = ctx.register(unique[:total])
        rec["found"] = len(fresh)
    if fresh:
        ctx.emit("sources", SourcesEvent(sources=fresh))
    return fresh


# --- ingest ----------------------------------------------------------------------------------------
@dataclass
class IngestResult:
    doc_ids: list[str]
    read: list[Source]
    failed: list[Source]


def _friendly(exc: BaseException) -> str:
    return exc.message if isinstance(exc, GleanWiseError) else "Could not read this page."


async def ingest_stage(
    ctx: RunContext, sources: list[Source], *, budget_s: float, announce_visits: bool = False
) -> IngestResult:
    s = ctx.settings
    doc_ids: list[str] = []
    read: list[Source] = []
    failed: list[Source] = []
    if not sources:  # e.g. a Deep round whose searches only returned pages we already have
        return IngestResult(doc_ids=[], read=[], failed=[])

    async def one(src: Source) -> None:
        ctx.emit("source_update", SourceUpdateEvent(id=src.id, state="reading"))
        try:
            page = await ctx.svc.fetcher.fetch(
                src.url, ttl_class=ctx.ttl_class, cache=not ctx.req.private
            )
            doc = page.doc
            if not (page.from_cache and await ctx.svc.store.chunk_count(doc.id) > 0):
                chunks = await asyncio.to_thread(
                    chunk_document,
                    doc.text,
                    url=doc.url,
                    doc_id=doc.id,
                    max_tokens=s.chunk_tokens,
                    overlap_tokens=s.chunk_overlap_tokens,
                )
                await ctx.svc.store.replace_chunks(doc.id, chunks)
            if doc.title and not src.title.strip():
                src.title = doc.title
            if page.published_at and not src.published_at:
                src.published_at = page.published_at
            ctx.doc_source[doc.id] = src
            doc_ids.append(doc.id)
            read.append(src)
            metrics.FETCHES.labels("cache" if page.from_cache else "ok").inc()
            ctx.emit("source_update", SourceUpdateEvent(id=src.id, state="read"))
            if announce_visits:
                ctx.emit(
                    "visit",
                    VisitEvent(source_id=src.id, url=src.url, title=src.title, round=ctx.round),
                )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            failed.append(src)
            metrics.FETCHES.labels(getattr(exc, "code", "error")).inc()
            if not isinstance(exc, GleanWiseError):
                log.warning("ingest failed for %s: %r", src.url, exc)
            ctx.emit(
                "source_update", SourceUpdateEvent(id=src.id, state="failed", reason=_friendly(exc))
            )

    async with ctx.stage("ingest", pages=len(sources)) as rec:
        tasks = {asyncio.create_task(one(src)): src for src in sources}
        try:
            _done, pending = await asyncio.wait(tasks, timeout=budget_s)
        except asyncio.CancelledError:
            for t in tasks:
                t.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            raise
        for t in pending:
            t.cancel()
            src = tasks[t]
            ctx.emit(
                "source_update",
                SourceUpdateEvent(id=src.id, state="skipped", reason="Took too long to load."),
            )
        await asyncio.gather(*pending, return_exceptions=True)
        rec.update(read=len(read), failed=len(failed), skipped=len(pending))
    for src in read:
        ctx.sources[src.id] = src
    return IngestResult(doc_ids=doc_ids, read=read, failed=failed)


# --- retrieve -------------------------------------------------------------------------------------
async def retrieve_stage(
    ctx: RunContext, queries: list[str], doc_ids: list[str], *, k: int
) -> RetrievalResult:
    async with ctx.stage("retrieve", docs=len(doc_ids), k=k) as rec:
        res = await retrieve(
            store=ctx.svc.store,
            embedder=ctx.svc.embedder,
            reranker=ctx.svc.reranker,
            queries=queries,
            doc_ids=doc_ids,
            k=k,
            warn=ctx.warn,
        )
        rec["chunks"] = len(res.chunks)
        rec["degraded"] = res.degraded
    if "reranker" in res.degraded:
        ctx.warn(
            "reranker_degraded", "Using keyword ranking because the relevance model is unavailable."
        )
    return res


def fit_budget(chunks: list[Chunk], budget: int) -> list[Chunk]:
    out: list[Chunk] = []
    used = 0
    for c in chunks:
        if used + len(c.text) > budget and out:
            continue
        out.append(c)
        used += len(c.text)
    return out


# --- answer -----------------------------------------------------------------------------------------
async def stream_answer(
    ctx: RunContext, query: str, context: str, *, note: str = "", draft: bool = False
) -> str:
    msgs = prompts.answer_messages(
        mode=ctx.mode,
        query=query,
        context=context,
        history=ctx.history,
        locale=ctx.locale,
        instructions=ctx.req.instructions,
        note=note,
    )
    parts: list[str] = []
    async with ctx.stage("answer"):
        async for d in ctx.svc.llm.stream(msgs, model=ctx.model, usage=ctx.usage):
            if d.kind == "reasoning":
                ctx.emit("reasoning_delta", ReasoningDeltaEvent(text=d.text, round=ctx.round))
                continue
            ctx.note_first_token()
            parts.append(d.text)
            ctx.emit("answer_delta", AnswerDeltaEvent(text=d.text, draft=draft))
    text = "".join(parts).strip()
    if not text:
        from gleanwise.errors import LLMError

        raise LLMError(
            "The model returned an empty answer.",
            hint="Retry, or pick a different model in Settings.",
        )
    return text


def complete_answer(ctx: RunContext, text: str, chunks: list[Chunk]) -> tuple[str, list[Citation]]:
    excerpts: dict[int, str] = {}
    for c in chunks:  # chunks are best-first, so the first per source is its best passage
        src = ctx.doc_source.get(c.doc_id)
        if src and src.id not in excerpts:
            excerpts[src.id] = truncate(" ".join(c.text.split()), 280)
    final, citations = finalize_answer(text, ctx.sources, excerpts)
    used = {c.number for c in citations}
    for sid, s in ctx.sources.items():
        s.used_in_answer = sid in used
    ctx.emit("answer_complete", AnswerCompleteEvent(text=final, citations=citations))
    return final, citations


async def follow_ups(ctx: RunContext, query: str, answer: str) -> list[str]:
    async with ctx.stage("follow_ups"):
        try:
            data = await ctx.svc.llm.complete_json(
                prompts.followup_messages(query, answer),
                model=ctx.model,
                usage=ctx.usage,
                max_tokens=220,
                timeout=12,
            )
        except GleanWiseError:
            return []
    qs = [q.strip() for q in data.get("questions", []) if isinstance(q, str) and q.strip()][:3]
    if qs:
        ctx.emit("follow_ups", FollowUpsEvent(questions=qs))
    return qs
