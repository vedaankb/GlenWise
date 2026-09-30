# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Ved Buddaraju

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import numpy as np
import pytest

from gleanwise.chunk.segment import chunk_document
from gleanwise.index.sqlite import SQLiteStore
from gleanwise.models import Document
from gleanwise.util.text import canonicalize_url, fts_query, sha1_hex


@pytest.fixture(params=["sqlite", "postgres"])
async def store(request, tmp_path):
    if request.param == "sqlite":
        s = SQLiteStore(tmp_path / "t.db")
    else:
        import asyncpg

        from gleanwise.index.postgres import PostgresStore

        uri = request.getfixturevalue("pg_uri")
        c = await asyncpg.connect(uri)
        await c.execute("DROP SCHEMA public CASCADE; CREATE SCHEMA public;")  # clean slate per test
        await c.close()
        s = PostgresStore(uri)
    await s.init()
    yield s
    await s.close()


def _doc(url: str, text: str) -> Document:
    c = canonicalize_url(url)
    now = datetime.now(UTC)
    return Document(
        id=sha1_hex(c, length=16),
        url=url,
        canonical_url=c,
        title="T",
        text=text,
        fetched_at=now,
        expires_at=now + timedelta(hours=1),
    )


async def _ingest(store, url: str, text: str, dim: int = 8, seed: int = 0):
    doc = _doc(url, text)
    await store.put_document(doc)
    chunks = chunk_document(text, url=url, doc_id=doc.id, max_tokens=30, overlap_tokens=5)
    await store.replace_chunks(doc.id, chunks)
    rng = np.random.default_rng(seed)
    await store.set_vectors([c.id for c in chunks], rng.normal(size=(len(chunks), dim)), "m")
    return doc, chunks


TEXT = (
    "# Heat pumps\n\n"
    + "A heat pump moves heat from outside to inside using refrigerant. " * 8
    + "\n\n## Efficiency\n\n"
    + "Coefficient of performance measures efficiency of a heat pump. " * 8
)


async def test_migrations_and_wal(store):
    info = await store.ping()
    assert info["schema"] == 1
    if store.backend == "sqlite":
        assert info["vector_index"] in {"sqlite-vec", "numpy"}
        assert store.db.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
    else:
        assert info["vector_index"] == "pgvector"


async def test_chunks_are_deterministic_and_idempotent(store):
    doc, first = await _ingest(store, "https://a.test/x", TEXT)
    ids_first = sorted(c.id for c in first)
    _, second = await _ingest(store, "https://a.test/x", TEXT)
    assert ids_first == sorted(c.id for c in second)
    assert await store.chunk_count(doc.id) == len(first)  # no duplication on re-ingest


async def test_offsets_are_truthful():
    doc_id = "d"
    chunks = chunk_document(TEXT, url="u", doc_id=doc_id, max_tokens=30, overlap_tokens=5)
    assert len(chunks) > 3
    for c in chunks:
        assert TEXT[c.start : c.end] == c.text
    assert any(c.heading_path == "Heat pumps > Efficiency" for c in chunks)


async def test_bm25_scoped_and_hostile_queries(store):
    d1, _ = await _ingest(store, "https://a.test/1", TEXT)
    d2, _ = await _ingest(
        store,
        "https://b.test/2",
        "# Bread\n\n" + "Sourdough needs flour water salt and time. " * 10,
    )
    hits = await store.bm25("how do heat pumps work?", 5, None)
    assert hits and all(c.doc_id == d1.id for c, _ in hits)
    assert await store.bm25("heat pump", 5, [d2.id]) == []  # scoped
    # FTS5 operator soup must never raise.
    for q in [
        '"unbalanced',
        "NEAR(",
        "a AND",
        "col:val",
        "*",
        "-x",
        "C++ / 100%",
        "'; DROP TABLE chunks;--",
    ]:
        await store.bm25(q, 5, None)
    assert fts_query("   ") is None


async def test_dense_scoped_and_global(store):
    d1, c1 = await _ingest(store, "https://a.test/1", TEXT, seed=1)
    d2, c2 = await _ingest(store, "https://b.test/2", TEXT + " extra words to differ.", seed=2)
    rng = np.random.default_rng(1)
    q = rng.normal(size=(len(c1), 8))[0]
    scoped = await store.dense(q, 3, [d1.id], "m")
    assert scoped and scoped[0][0].doc_id == d1.id and scoped[0][1] > 0.99
    assert all(c.doc_id == d1.id for c, _ in scoped)
    global_hits = await store.dense(q, 3, None, "m")
    assert global_hits and global_hits[0][1] > 0.99
    assert await store.dense(q, 3, None, "other-model") == []  # model isolation


async def test_replace_removes_vectors_and_fts(store):
    doc, chunks = await _ingest(store, "https://a.test/1", TEXT)
    await store.replace_chunks(doc.id, [])
    assert await store.chunk_count(doc.id) == 0
    assert await store.bm25("heat pump", 5, None) == []
    assert await store.dense(np.ones(8), 5, None, "m") == []


async def test_threads_turns_history_and_search(store):
    t = await store.create_thread("Heat pumps")
    assert await store.list_threads(None, 10, 0) == []  # empty threads are hidden
    msg = await store.add_turn(
        t.id,
        {"role": "user", "content": "how do heat pumps work?"},
        {
            "role": "assistant",
            "content": "They move heat [1].",
            "mode": "quick",
            "citations": [{"number": 1, "url": "https://a.test", "source_id": 1}],
            "query_id": "q1",
        },
    )
    assert msg.citations[0].number == 1
    threads = await store.list_threads(None, 10, 0)
    assert [x.id for x in threads] == [t.id] and threads[0].mode.value == "quick"
    assert [x.id for x in await store.list_threads("refrigerant", 10, 0)] == []
    assert [x.id for x in await store.list_threads("heat", 10, 0)] == [t.id]
    assert [x.id for x in await store.list_threads("100%", 10, 0)] == []  # LIKE wildcards escaped
    hist = await store.history(t.id, 10)
    assert [h.role for h in hist] == ["user", "assistant"]
    assert await store.update_thread(t.id, "Renamed", True)
    detail = await store.get_thread(t.id)
    assert detail and detail.title == "Renamed" and detail.pinned
    assert await store.delete_thread(t.id)
    assert await store.get_thread(t.id) is None


async def test_traces_feedback_purge(store):
    await store.add_trace("q1", None, {"a": 1})
    assert (await store.list_traces(5))[0] == {"a": 1}
    await store.add_feedback("q1", 1, "nice")
    assert (await store.list_feedback(5))[0].thumb == 1
    assert await store.purge_traces(0) >= 1
