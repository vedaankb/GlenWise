# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Ved Buddaraju

"""Quick / Pro / Deep — each is a composition of the stages in ``stages.py``."""

from __future__ import annotations

import asyncio
import contextlib
from dataclasses import dataclass, field
from typing import Any

from gleanwise.errors import FetchFailed, GleanWiseError
from gleanwise.llm import prompts
from gleanwise.models import (
    AnswerDeltaEvent,
    AnswerUpgradeEvent,
    Citation,
    Mode,
    PlanEvent,
    ReasoningDeltaEvent,
)
from gleanwise.pipeline import stages
from gleanwise.pipeline.context import RunContext
from gleanwise.util.text import truncate


@dataclass
class Answer:
    text: str
    citations: list[Citation]
    follow_ups: list[str] = field(default_factory=list)
    research_summary: str | None = None
    research_log: list[dict[str, Any]] | None = None


def _plan_event(
    ctx: RunContext, steps: list[str], rewritten: str | None, subqueries: list[str]
) -> None:
    ctx.emit(
        "plan",
        PlanEvent(steps=steps, mode=ctx.mode, rewritten_query=rewritten, subqueries=subqueries),
    )


def _context_from_chunks(ctx: RunContext, chunks: list[Any]) -> str:
    budget = stages.CONTEXT_BUDGET_CHARS[ctx.mode.value]
    return prompts.context_block(stages.fit_budget(chunks, budget), ctx.doc_source)


async def run_quick(ctx: RunContext) -> Answer:
    _plan_event(ctx, ["Search the web", "Read the best sources", "Write a cited answer"], None, [])
    query = await stages.rewrite_query(ctx)
    found = await stages.search_stage(ctx, [query], per_query=8, total=8)
    top = found[:5]

    snippets = prompts.snippet_block(found[:6])
    draft: str | None = None
    ingest_task = asyncio.create_task(stages.ingest_stage(ctx, top, budget_s=12))
    try:
        if ctx.settings.quick_two_pass and ctx.req.draft and snippets:
            try:
                draft = await stages.stream_answer(
                    ctx,
                    query,
                    snippets,
                    note="Only short search-result snippets are available; keep it brief and hedge appropriately.",
                    draft=True,
                )
            except GleanWiseError as exc:
                if exc.code in {"llm_not_configured", "llm_auth", "llm_model_not_found"}:
                    raise
                draft = None
        ing = await ingest_task
    finally:
        if not ingest_task.done():
            ingest_task.cancel()
            await asyncio.gather(ingest_task, return_exceptions=True)

    if not ing.doc_ids:
        if draft is None:
            if not snippets:
                raise FetchFailed(
                    "None of the top pages could be read.",
                    hint="They may block automated readers. Try rephrasing or use Pro mode.",
                    action="retry",
                )
            draft = await stages.stream_answer(
                ctx, query, snippets, note="Only short snippets are available."
            )
        ctx.warn(
            "snippets_only", "Answer is based on search snippets; the pages could not be opened."
        )
        text, cites = stages.complete_answer(ctx, draft, [])
        return Answer(text, cites)

    res = await stages.retrieve_stage(ctx, [query], ing.doc_ids, k=7)
    if draft is not None:
        ctx.emit("answer_upgrade", AnswerUpgradeEvent(reason="full_pages"))
    try:
        final = await stages.stream_answer(ctx, query, _context_from_chunks(ctx, res.chunks))
    except GleanWiseError:
        if draft is None:
            raise
        # Keep the user's answer: clear the half-written upgrade and restore the draft verbatim.
        ctx.warn(
            "upgrade_failed",
            "Could not refine the answer with full pages; showing the snippet-based draft.",
        )
        ctx.emit("answer_upgrade", AnswerUpgradeEvent(reason="restore_draft"))
        ctx.emit("answer_delta", AnswerDeltaEvent(text=draft))
        text, cites = stages.complete_answer(ctx, draft, [])
        return Answer(text, cites)
    text, cites = stages.complete_answer(ctx, final, res.chunks)
    return Answer(text, cites)


async def run_pro(ctx: RunContext) -> Answer:
    _plan_event(
        ctx,
        [
            "Understand the question",
            "Plan searches",
            "Search and read sources",
            "Synthesise a cited answer",
        ],
        None,
        [],
    )
    query = await stages.rewrite_query(ctx)
    queries = await stages.make_plan(ctx, query, 3)
    _plan_event(
        ctx,
        [
            "Understand the question",
            "Plan searches",
            "Search and read sources",
            "Synthesise a cited answer",
        ],
        query if query != ctx.req.query else None,
        queries,
    )
    found = await stages.search_stage(ctx, queries, per_query=8, total=14)
    ing = await stages.ingest_stage(ctx, found[:10], budget_s=28)
    if not ing.doc_ids:
        snippets = prompts.snippet_block(found)
        if not snippets:
            raise FetchFailed(
                "None of the sources could be read.",
                hint="Try again, or rephrase the question.",
                action="retry",
            )
        ctx.warn(
            "snippets_only", "Answer is based on search snippets; the pages could not be opened."
        )
        chunks: list[Any] = []
        final = await stages.stream_answer(ctx, query, snippets)
    else:
        res = await stages.retrieve_stage(ctx, queries, ing.doc_ids, k=14)
        chunks = res.chunks
        final = await stages.stream_answer(ctx, query, _context_from_chunks(ctx, chunks))
    text, cites = stages.complete_answer(ctx, final, chunks)
    fu = await stages.follow_ups(ctx, query, text)
    return Answer(text, cites, fu)


async def run_deep(ctx: RunContext) -> Answer:
    steps = ["Plan the research", "Search and read in rounds", "Check for gaps", "Write the report"]
    _plan_event(ctx, steps, None, [])
    query = await stages.rewrite_query(ctx)
    queries = await stages.make_plan(ctx, query, 4)
    _plan_event(ctx, steps, query if query != ctx.req.query else None, queries)

    all_queries = list(queries)
    doc_ids: list[str] = []
    read_total = found_total = 0
    max_rounds = ctx.settings.deep_max_rounds
    reserve = max(60.0, ctx.deadline_s * 0.25)  # always leave time to write the report
    round_queries = queries
    rounds_done = 0

    for rnd in range(1, max_rounds + 1):
        ctx.round = rnd
        narrate = f"Round {rnd}: searching {len(round_queries)} queries — " + "; ".join(
            truncate(q, 60) for q in round_queries
        )
        ctx.emit("reasoning_delta", ReasoningDeltaEvent(text=narrate + "\n", round=rnd))
        try:
            found = await stages.search_stage(ctx, round_queries, per_query=8, total=12)
        except GleanWiseError as exc:
            if rnd == 1:
                raise
            ctx.emit(
                "reasoning_delta",
                ReasoningDeltaEvent(
                    text=f"Search failed ({exc.message}); continuing with what was found.\n",
                    round=rnd,
                ),
            )
            break
        found_total += len(found)
        budget = min(35.0, max(8.0, ctx.time_left() - reserve))
        ing = await stages.ingest_stage(ctx, found[:8], budget_s=budget, announce_visits=True)
        doc_ids.extend(d for d in ing.doc_ids if d not in doc_ids)
        read_total += len(ing.read)
        rounds_done = rnd
        log_entry: dict[str, Any] = {
            "round": rnd,
            "queries": round_queries,
            "found": len(found),
            "read": len(ing.read),
            "visited": [{"id": s.id, "url": s.url, "title": s.title} for s in ing.read],
        }
        ctx.research_log.append(log_entry)
        ctx.emit(
            "reasoning_delta",
            ReasoningDeltaEvent(
                text=f"Read {len(ing.read)} of {len(found)} new pages.\n", round=rnd
            ),
        )

        if rnd == max_rounds or ctx.time_left() < reserve + 25:
            break
        if not doc_ids:
            continue
        # Gap check: real LLM judgement over what has actually been collected so far.
        notes_res = await stages.retrieve_stage(ctx, [query, *all_queries[:3]], doc_ids, k=8)
        notes = "\n\n".join(
            f"[{ctx.doc_source[c.doc_id].id}] {truncate(' '.join(c.text.split()), 420)}"
            for c in notes_res.chunks
            if c.doc_id in ctx.doc_source
        )
        try:
            verdict = await ctx.svc.llm.complete_json(
                prompts.critic_messages(query, notes, all_queries),
                model=ctx.model,
                usage=ctx.usage,
                max_tokens=350,
                timeout=30,
            )
        except GleanWiseError as exc:
            if exc.code in {"llm_not_configured", "llm_auth", "llm_model_not_found"}:
                raise
            verdict = {}
        reasoning = str(verdict.get("reasoning") or "").strip()
        new_qs = [
            q.strip()
            for q in verdict.get("queries", [])
            if isinstance(q, str) and q.strip() and q.strip() not in all_queries
        ][:3]
        log_entry["reasoning"] = reasoning
        log_entry["sufficient"] = bool(verdict.get("sufficient"))
        if reasoning:
            ctx.emit(
                "reasoning_delta", ReasoningDeltaEvent(text=f"Assessment: {reasoning}\n", round=rnd)
            )
        if verdict.get("sufficient") or not new_qs:
            break
        all_queries.extend(new_qs)
        round_queries = new_qs

    ctx.round = None
    if not doc_ids:
        raise FetchFailed(
            "None of the sources could be read.",
            hint="Try again or rephrase the question.",
            action="retry",
        )

    res = await stages.retrieve_stage(ctx, [query, *all_queries[:4]], doc_ids, k=22)
    ctx.emit(
        "reasoning_delta",
        ReasoningDeltaEvent(text="Writing the report from the strongest passages.\n", round=None),
    )
    final = await stages.stream_answer(ctx, query, _context_from_chunks(ctx, res.chunks))
    text, cites = stages.complete_answer(ctx, final, res.chunks)
    fu: list[str] = []
    with contextlib.suppress(GleanWiseError):
        fu = await stages.follow_ups(ctx, query, text)
    summary = f"{rounds_done} research round{'s' if rounds_done != 1 else ''}, {len(all_queries)} searches, read {read_total} of {found_total} pages."
    return Answer(text, cites, fu, research_summary=summary, research_log=ctx.research_log)


RUNNERS = {Mode.quick: run_quick, Mode.pro: run_pro, Mode.deep: run_deep}
