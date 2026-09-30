# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Ved Buddaraju

"""Scoped hybrid retrieval: BM25 + dense fused with RRF, then cross-encoder rerank."""

from __future__ import annotations

import logging
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass

from gleanwise.embed.embedder import Embedder
from gleanwise.index.base import Store
from gleanwise.models import Chunk
from gleanwise.rank.reranker import Reranker

log = logging.getLogger(__name__)

RRF_K = 60
EMBED_ALL_BELOW = 160  # embed every new chunk when the corpus is small
EMBED_CAP = 220


def rrf(rankings: list[list[str]], k: int = RRF_K) -> dict[str, float]:
    scores: dict[str, float] = defaultdict(float)
    for ranking in rankings:
        for rank, cid in enumerate(ranking):
            scores[cid] += 1.0 / (k + rank + 1)
    return scores


def embed_text(c: Chunk) -> str:
    head = f"{c.heading_path}\n" if c.heading_path else ""
    return (head + c.text)[:1800]


@dataclass
class RetrievalResult:
    chunks: list[Chunk]
    degraded: list[str]


async def retrieve(
    *,
    store: Store,
    embedder: Embedder,
    reranker: Reranker,
    queries: list[str],
    doc_ids: list[str] | None,
    k: int,
    per_doc: int = 3,
    warn: Callable[[str, str], None] | None = None,
) -> RetrievalResult:
    """Return the ``k`` best chunks *from ``doc_ids`` only* for ``queries[0]`` (+ expansions)."""
    degraded: list[str] = []
    global_mode = doc_ids is None  # search everything already indexed; embeds nothing new
    if (doc_ids is not None and not doc_ids) or not queries:
        return RetrievalResult([], degraded)
    main = queries[0]

    bm_lists: list[list[str]] = []
    pool: dict[str, Chunk] = {}
    for q in queries:
        hits = await store.bm25(q, 80, doc_ids)
        bm_lists.append([c.id for c, _ in hits])
        pool.update({c.id: c for c, _ in hits})

    # --- dense side: embed only what is worth embedding --------------------------------------
    dense_lists: list[list[str]] = []
    try:
        needing = (
            [] if doc_ids is None else await store.chunks_needing_vectors(doc_ids, embedder.name)
        )
        if doc_ids is not None and len(needing) > EMBED_ALL_BELOW:
            wanted = {cid for lst in bm_lists for cid in lst[:100]}
            leads = {c.id for c in await store.lead_chunks(doc_ids, 2)}
            needing = [c for c in needing if c.id in wanted or c.id in leads][:EMBED_CAP]
        if needing:
            vecs = await embedder.embed([embed_text(c) for c in needing], "passage")
            await store.set_vectors([c.id for c in needing], vecs, embedder.name)
        qvecs = await embedder.embed(queries, "query")
        for qv in qvecs:
            hits = await store.dense(qv, 60, doc_ids, embedder.name)
            dense_lists.append([c.id for c, _ in hits])
            pool.update({c.id: c for c, _ in hits})
    except Exception as exc:  # embeddings are an enhancement; keyword retrieval still answers
        log.warning("dense retrieval unavailable: %r", exc)
        degraded.append("embeddings")
        if warn:
            warn(
                "embeddings_unavailable",
                "Semantic search is unavailable; using keyword matching only.",
            )

    fused = rrf([*bm_lists, *dense_lists])
    if not fused:  # nothing matched at all → fall back to the openings of each page
        openings = [] if global_mode or doc_ids is None else await store.lead_chunks(doc_ids, 2)
        return RetrievalResult(openings[:k], degraded)
    ranked = sorted(fused, key=lambda cid: fused[cid], reverse=True)[:32]
    cands = [pool[cid] for cid in ranked]

    scores = await reranker.score(main, [embed_text(c) for c in cands])
    if reranker.degraded_reason:
        degraded.append("reranker")
    order = sorted(range(len(cands)), key=lambda i: (scores[i], fused[cands[i].id]), reverse=True)

    out: list[Chunk] = []
    count: dict[str, int] = defaultdict(int)
    for i in order:
        c = cands[i]
        if count[c.doc_id] >= per_doc:
            continue
        count[c.doc_id] += 1
        out.append(c.model_copy(update={"score": float(scores[i])}))
        if len(out) >= k:
            break
    return RetrievalResult(out, degraded)
