# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Ved Buddaraju

"""Postgres backend (server profile): pgvector for dense search, tsvector (or ParadeDB) for BM25.

Same contract and semantics as ``SQLiteStore``; schema is migrated with a ``schema_migrations`` table.
"""

from __future__ import annotations

import json
import logging
import re
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import numpy as np

from gleanwise.index.base import Scored
from gleanwise.models import (
    Chunk,
    Citation,
    Document,
    FeedbackOut,
    Focus,
    MessageOut,
    Mode,
    Source,
    ThreadDetail,
    ThreadSummary,
    Turn,
)
from gleanwise.util.text import content_tokens, tokens

log = logging.getLogger(__name__)

MIGRATIONS: list[str] = [
    """
    CREATE EXTENSION IF NOT EXISTS vector;
    CREATE TABLE documents (
      id text PRIMARY KEY, url text NOT NULL, canonical_url text NOT NULL UNIQUE,
      title text NOT NULL DEFAULT '', content_type text NOT NULL DEFAULT 'text/html',
      etag text, last_modified text, fetched_at timestamptz, expires_at timestamptz,
      ttl_class text NOT NULL DEFAULT 'default', text text NOT NULL DEFAULT ''
    );
    CREATE INDEX documents_expires ON documents(expires_at);
    CREATE TABLE chunks (
      id text PRIMARY KEY, doc_id text NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
      url text NOT NULL, heading_path text NOT NULL DEFAULT '', text text NOT NULL,
      start int NOT NULL DEFAULT 0, "end" int NOT NULL DEFAULT 0,
      embedding_model text, dim int, embedding vector,
      tsv tsvector GENERATED ALWAYS AS (to_tsvector('simple', heading_path || ' ' || text)) STORED
    );
    CREATE INDEX chunks_doc ON chunks(doc_id);
    CREATE INDEX chunks_model ON chunks(embedding_model);
    CREATE INDEX chunks_tsv ON chunks USING gin(tsv);
    CREATE TABLE threads (
      id text PRIMARY KEY, title text NOT NULL, pinned boolean NOT NULL DEFAULT false,
      created_at timestamptz NOT NULL, updated_at timestamptz NOT NULL
    );
    CREATE INDEX threads_updated ON threads(pinned DESC, updated_at DESC);
    CREATE TABLE messages (
      id text PRIMARY KEY, thread_id text NOT NULL REFERENCES threads(id) ON DELETE CASCADE,
      seq bigserial, role text NOT NULL, content text NOT NULL,
      citations jsonb NOT NULL DEFAULT '[]', sources jsonb NOT NULL DEFAULT '[]',
      mode text, focus text, query_id text, research_summary text, research_log jsonb,
      follow_ups jsonb NOT NULL DEFAULT '[]', created_at timestamptz NOT NULL
    );
    CREATE INDEX messages_thread ON messages(thread_id, seq);
    CREATE TABLE feedback (id bigserial PRIMARY KEY, query_id text NOT NULL, thumb int NOT NULL, comment text, created_at timestamptz NOT NULL);
    CREATE TABLE traces (id bigserial PRIMARY KEY, query_id text NOT NULL, thread_id text, payload jsonb NOT NULL, created_at timestamptz NOT NULL);
    CREATE INDEX traces_created ON traces(created_at);
    """,
]

_CHUNK_COLS = (
    'c.id, c.doc_id, c.url, c.heading_path, c.text, c.start, c."end", c.embedding_model, c.dim'
)


def _now() -> datetime:
    return datetime.now(UTC)


def _vec(v: np.ndarray) -> str:
    return "[" + ",".join(f"{float(x):.7g}" for x in v) + "]"


def _unit(mat: np.ndarray) -> np.ndarray:
    n = np.linalg.norm(mat, axis=1, keepdims=True)
    n[n == 0] = 1.0
    return (mat / n).astype(np.float32)


def _tsquery(text: str) -> str | None:
    terms = content_tokens(text, 24) or tokens(text)[:24]
    terms = [re.sub(r"\W", "", t) for t in terms]
    terms = [t for t in terms if t]
    return " | ".join(terms) if terms else None


class PostgresStore:
    backend = "postgres"

    def __init__(self, dsn: str) -> None:
        self.dsn = dsn
        self.pool: Any = None
        self._dims: set[int] = set()

    async def init(self) -> None:
        import asyncpg

        async def setup(conn: Any) -> None:
            await conn.set_type_codec(
                "jsonb", encoder=json.dumps, decoder=json.loads, schema="pg_catalog"
            )

        self.pool = await asyncpg.create_pool(
            self.dsn, min_size=1, max_size=10, init=setup, command_timeout=30
        )
        async with self.pool.acquire() as c:
            await c.execute(
                "CREATE TABLE IF NOT EXISTS schema_migrations (version int PRIMARY KEY, applied_at timestamptz NOT NULL DEFAULT now())"
            )
            await c.execute(
                "SELECT pg_advisory_lock(727272)"
            )  # serialise concurrent workers starting together
            try:
                current = await c.fetchval(
                    "SELECT COALESCE(MAX(version), 0) FROM schema_migrations"
                )
                for target, script in enumerate(MIGRATIONS, start=1):
                    if target <= current:
                        continue
                    async with c.transaction():
                        await c.execute(script)
                        await c.execute(
                            "INSERT INTO schema_migrations(version) VALUES ($1)", target
                        )
            finally:
                await c.execute("SELECT pg_advisory_unlock(727272)")

    async def close(self) -> None:
        if self.pool is not None:
            await self.pool.close()
            self.pool = None

    async def ping(self) -> dict[str, Any]:
        async with self.pool.acquire() as c:
            v = await c.fetchval("SELECT COALESCE(MAX(version), 0) FROM schema_migrations")
        return {"backend": "postgres", "schema": v, "vector_index": "pgvector"}

    async def stats(self) -> dict[str, int]:
        async with self.pool.acquire() as c:
            out = {}
            for t in ("documents", "chunks", "threads", "messages"):
                out[t] = int(await c.fetchval(f"SELECT COUNT(*) FROM {t}"))
        return out

    # -- documents & chunks -------------------------------------------------------------------
    @staticmethod
    def _doc(r: Any) -> Document:
        return Document(
            **{
                k: r[k]
                for k in (
                    "id",
                    "url",
                    "canonical_url",
                    "title",
                    "content_type",
                    "etag",
                    "last_modified",
                    "fetched_at",
                    "expires_at",
                    "ttl_class",
                    "text",
                )
            }
        )

    async def get_document(self, canonical_url: str) -> Document | None:
        async with self.pool.acquire() as c:
            r = await c.fetchrow("SELECT * FROM documents WHERE canonical_url=$1", canonical_url)
        return self._doc(r) if r else None

    async def get_documents(self, doc_ids: list[str]) -> dict[str, Document]:
        if not doc_ids:
            return {}
        async with self.pool.acquire() as c:
            rows = await c.fetch("SELECT * FROM documents WHERE id = ANY($1)", doc_ids)
        return {r["id"]: self._doc(r) for r in rows}

    async def put_document(self, doc: Document) -> None:
        async with self.pool.acquire() as c:
            await c.execute(
                """INSERT INTO documents(id,url,canonical_url,title,content_type,etag,last_modified,fetched_at,expires_at,ttl_class,text)
                   VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11)
                   ON CONFLICT (canonical_url) DO UPDATE SET url=EXCLUDED.url, title=EXCLUDED.title,
                     content_type=EXCLUDED.content_type, etag=EXCLUDED.etag, last_modified=EXCLUDED.last_modified,
                     fetched_at=EXCLUDED.fetched_at, expires_at=EXCLUDED.expires_at, ttl_class=EXCLUDED.ttl_class, text=EXCLUDED.text""",
                doc.id,
                doc.url,
                doc.canonical_url,
                doc.title,
                doc.content_type,
                doc.etag,
                doc.last_modified,
                doc.fetched_at,
                doc.expires_at,
                doc.ttl_class,
                doc.text,
            )

    async def touch_document(self, doc_id: str, fetched_at: datetime, expires_at: datetime) -> None:
        async with self.pool.acquire() as c:
            await c.execute(
                "UPDATE documents SET fetched_at=$2, expires_at=$3 WHERE id=$1",
                doc_id,
                fetched_at,
                expires_at,
            )

    async def chunk_count(self, doc_id: str) -> int:
        async with self.pool.acquire() as c:
            return int(await c.fetchval("SELECT COUNT(*) FROM chunks WHERE doc_id=$1", doc_id))

    async def replace_chunks(self, doc_id: str, chunks: list[Chunk]) -> None:
        async with self.pool.acquire() as c, c.transaction():
            await c.execute("DELETE FROM chunks WHERE doc_id=$1", doc_id)
            await c.executemany(
                'INSERT INTO chunks(id,doc_id,url,heading_path,text,start,"end") VALUES ($1,$2,$3,$4,$5,$6,$7) ON CONFLICT (id) DO NOTHING',
                [(x.id, x.doc_id, x.url, x.heading_path, x.text, x.start, x.end) for x in chunks],
            )

    @staticmethod
    def _chunk(r: Any, score: float | None = None) -> Chunk:
        return Chunk(
            id=r["id"],
            doc_id=r["doc_id"],
            url=r["url"],
            heading_path=r["heading_path"],
            text=r["text"],
            start=r["start"],
            end=r["end"],
            embedding_model=r["embedding_model"],
            dim=r["dim"],
            score=score,
        )

    async def lead_chunks(self, doc_ids: list[str], per_doc: int) -> list[Chunk]:
        if not doc_ids:
            return []
        async with self.pool.acquire() as c:
            rows = await c.fetch(
                f"""SELECT {_CHUNK_COLS} FROM (SELECT *, ROW_NUMBER() OVER (PARTITION BY doc_id ORDER BY start) rn
                    FROM chunks WHERE doc_id = ANY($1)) c WHERE rn <= $2""",
                doc_ids,
                per_doc,
            )
        return [self._chunk(r) for r in rows]

    async def chunks_needing_vectors(self, doc_ids: list[str], model: str) -> list[Chunk]:
        if not doc_ids:
            return []
        async with self.pool.acquire() as c:
            rows = await c.fetch(
                f"SELECT {_CHUNK_COLS} FROM chunks c WHERE doc_id = ANY($1) AND (embedding IS NULL OR embedding_model IS DISTINCT FROM $2)",
                doc_ids,
                model,
            )
        return [self._chunk(r) for r in rows]

    async def _ensure_index(self, c: Any, dim: int) -> None:
        if dim in self._dims or dim > 2000:
            return
        try:
            await c.execute(
                f"CREATE INDEX IF NOT EXISTS chunks_emb_{int(dim)} ON chunks USING hnsw (((embedding::vector({int(dim)}))) vector_cosine_ops) WHERE dim = {int(dim)}"
            )
        except Exception as exc:  # index is an optimisation only
            log.warning("could not create hnsw index for dim %s: %s", dim, exc)
        self._dims.add(dim)

    async def set_vectors(self, chunk_ids: list[str], vectors: np.ndarray, model: str) -> None:
        if not chunk_ids:
            return
        vectors = _unit(np.asarray(vectors, dtype=np.float32))
        dim = int(vectors.shape[1])
        async with self.pool.acquire() as c:
            await c.executemany(
                "UPDATE chunks SET embedding=$2::vector, embedding_model=$3, dim=$4 WHERE id=$1",
                [(cid, _vec(v), model, dim) for cid, v in zip(chunk_ids, vectors, strict=True)],
            )
            await self._ensure_index(c, dim)

    async def bm25(self, query: str, limit: int, doc_ids: list[str] | None) -> list[Scored]:
        q = _tsquery(query)
        if not q:
            return []
        sql = f"SELECT {_CHUNK_COLS}, ts_rank_cd(c.tsv, to_tsquery('simple', $1)) AS s FROM chunks c WHERE c.tsv @@ to_tsquery('simple', $1)"
        args: list[Any] = [q]
        if doc_ids is not None:
            if not doc_ids:
                return []
            sql += " AND c.doc_id = ANY($2)"
            args.append(doc_ids)
        sql += f" ORDER BY s DESC LIMIT {int(limit)}"
        async with self.pool.acquire() as c:
            rows = await c.fetch(sql, *args)
        return [(self._chunk(r, float(r["s"])), float(r["s"])) for r in rows]

    async def dense(
        self, vector: np.ndarray, limit: int, doc_ids: list[str] | None, model: str
    ) -> list[Scored]:
        q = _unit(np.asarray(vector, dtype=np.float32).reshape(1, -1))[0]
        dim = int(q.shape[0])
        expr = f"(c.embedding::vector({dim}))"
        sql = f"SELECT {_CHUNK_COLS}, 1 - ({expr} <=> $1::vector({dim})) AS s FROM chunks c WHERE c.dim = {dim} AND c.embedding_model = $2"
        args: list[Any] = [_vec(q), model]
        if doc_ids is not None:
            if not doc_ids:
                return []
            sql += " AND c.doc_id = ANY($3)"
            args.append(doc_ids)
        sql += f" ORDER BY {expr} <=> $1::vector({dim}) LIMIT {int(limit)}"
        async with self.pool.acquire() as c:
            rows = await c.fetch(sql, *args)
        return [(self._chunk(r, float(r["s"])), float(r["s"])) for r in rows]

    async def clear_index(self) -> None:
        async with self.pool.acquire() as c:
            await c.execute("TRUNCATE chunks, documents CASCADE")

    # -- threads & messages -------------------------------------------------------------------
    async def create_thread(self, title: str) -> ThreadSummary:
        tid, now = uuid.uuid4().hex, _now()
        title = title[:200] or "New thread"
        async with self.pool.acquire() as c:
            await c.execute(
                "INSERT INTO threads(id,title,pinned,created_at,updated_at) VALUES ($1,$2,false,$3,$3)",
                tid,
                title,
                now,
            )
        return ThreadSummary(id=tid, title=title, created_at=now, updated_at=now)

    @staticmethod
    def _message(r: Any) -> MessageOut:
        return MessageOut(
            id=r["id"],
            thread_id=r["thread_id"],
            role=r["role"],
            content=r["content"],
            citations=[Citation(**x) for x in r["citations"]],
            sources=[Source(**x) for x in r["sources"]],
            mode=Mode(r["mode"]) if r["mode"] else None,
            focus=Focus(r["focus"]) if r["focus"] else None,
            created_at=r["created_at"],
            query_id=r["query_id"],
            research_summary=r["research_summary"],
            research_log=r["research_log"],
            follow_ups=r["follow_ups"],
        )

    async def get_thread(self, thread_id: str) -> ThreadDetail | None:
        async with self.pool.acquire() as c:
            t = await c.fetchrow("SELECT * FROM threads WHERE id=$1", thread_id)
            if t is None:
                return None
            msgs = await c.fetch(
                "SELECT * FROM messages WHERE thread_id=$1 ORDER BY seq", thread_id
            )
        return ThreadDetail(
            id=t["id"],
            title=t["title"],
            pinned=t["pinned"],
            created_at=t["created_at"],
            updated_at=t["updated_at"],
            messages=[self._message(m) for m in msgs],
        )

    async def list_threads(self, q: str | None, limit: int, offset: int) -> list[ThreadSummary]:
        sql = (
            "SELECT t.*, (SELECT m.mode FROM messages m WHERE m.thread_id=t.id AND m.role='assistant' ORDER BY m.seq DESC LIMIT 1) AS mode "
            "FROM threads t WHERE EXISTS (SELECT 1 FROM messages m WHERE m.thread_id=t.id)"
        )
        args: list[Any] = []
        if q and q.strip():
            like = (
                "%" + q.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
            )
            sql += " AND (t.title ILIKE $1 OR EXISTS (SELECT 1 FROM messages m WHERE m.thread_id=t.id AND m.content ILIKE $1))"
            args.append(like)
        sql += f" ORDER BY t.pinned DESC, t.updated_at DESC LIMIT {int(limit)} OFFSET {int(offset)}"
        async with self.pool.acquire() as c:
            rows = await c.fetch(sql, *args)
        return [
            ThreadSummary(
                id=r["id"],
                title=r["title"],
                pinned=r["pinned"],
                created_at=r["created_at"],
                updated_at=r["updated_at"],
                mode=Mode(r["mode"]) if r["mode"] else None,
            )
            for r in rows
        ]

    async def update_thread(self, thread_id: str, title: str | None, pinned: bool | None) -> bool:
        async with self.pool.acquire() as c:
            row = await c.fetchrow(
                "UPDATE threads SET title=COALESCE($2,title), pinned=COALESCE($3,pinned) WHERE id=$1 RETURNING id",
                thread_id,
                title[:200] if title is not None else None,
                pinned,
            )
        return row is not None

    async def delete_thread(self, thread_id: str) -> bool:
        async with self.pool.acquire() as c:
            return (await c.execute("DELETE FROM threads WHERE id=$1", thread_id)) == "DELETE 1"

    async def add_turn(
        self, thread_id: str, user: dict[str, Any], assistant: dict[str, Any]
    ) -> MessageOut:
        now, aid = _now(), uuid.uuid4().hex
        async with self.pool.acquire() as c, c.transaction():
            for mid, msg, off in ((uuid.uuid4().hex, user, 0), (aid, assistant, 1)):
                await c.execute(
                    """INSERT INTO messages(id,thread_id,role,content,citations,sources,mode,focus,query_id,research_summary,research_log,follow_ups,created_at)
                       VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13)""",
                    mid,
                    thread_id,
                    msg["role"],
                    msg["content"],
                    msg.get("citations", []),
                    msg.get("sources", []),
                    msg.get("mode"),
                    msg.get("focus"),
                    msg.get("query_id"),
                    msg.get("research_summary"),
                    msg.get("research_log"),
                    msg.get("follow_ups", []),
                    now + timedelta(microseconds=off),
                )
            await c.execute("UPDATE threads SET updated_at=$2 WHERE id=$1", thread_id, now)
            row = await c.fetchrow("SELECT * FROM messages WHERE id=$1", aid)
        return self._message(row)

    async def history(self, thread_id: str, limit: int) -> list[Turn]:
        async with self.pool.acquire() as c:
            rows = await c.fetch(
                "SELECT role, content FROM messages WHERE thread_id=$1 ORDER BY seq DESC LIMIT $2",
                thread_id,
                limit,
            )
        return [Turn(role=r["role"], content=r["content"]) for r in reversed(rows)]

    async def delete_message(self, message_id: str) -> bool:
        async with self.pool.acquire() as c, c.transaction():
            row = await c.fetchrow(
                "SELECT thread_id, role, seq FROM messages WHERE id=$1", message_id
            )
            if row is None:
                return False
            if row["role"] == "assistant":
                await c.execute(
                    "DELETE FROM messages WHERE id = (SELECT id FROM messages WHERE thread_id=$1 AND role='user' AND seq < $2 ORDER BY seq DESC LIMIT 1)",
                    row["thread_id"],
                    row["seq"],
                )
            await c.execute("DELETE FROM messages WHERE id=$1", message_id)
        return True

    async def purge_threads(self, older_than_days: int) -> int:
        async with self.pool.acquire() as c:
            n = 0
            if older_than_days > 0:
                r = await c.execute(
                    "DELETE FROM threads WHERE NOT pinned AND updated_at < now() - make_interval(days => $1)",
                    older_than_days,
                )
                n += int(r.split()[-1])
            r = await c.execute(
                "DELETE FROM threads t WHERE updated_at < now() - interval '1 day' AND NOT EXISTS (SELECT 1 FROM messages m WHERE m.thread_id=t.id)"
            )
            return n + int(r.split()[-1])

    async def wipe_user_data(self) -> None:
        async with self.pool.acquire() as c:
            await c.execute("TRUNCATE messages, threads, feedback, traces CASCADE")

    # -- feedback & traces --------------------------------------------------------------------
    async def add_feedback(self, query_id: str, thumb: int, comment: str | None) -> None:
        async with self.pool.acquire() as c:
            await c.execute(
                "INSERT INTO feedback(query_id,thumb,comment,created_at) VALUES ($1,$2,$3,now())",
                query_id,
                thumb,
                comment,
            )

    async def list_feedback(self, limit: int) -> list[FeedbackOut]:
        async with self.pool.acquire() as c:
            rows = await c.fetch("SELECT * FROM feedback ORDER BY id DESC LIMIT $1", limit)
        return [
            FeedbackOut(
                query_id=r["query_id"],
                thumb=r["thumb"],
                comment=r["comment"],
                created_at=r["created_at"],
            )
            for r in rows
        ]

    async def add_trace(
        self, query_id: str, thread_id: str | None, payload: dict[str, Any]
    ) -> None:
        async with self.pool.acquire() as c:
            await c.execute(
                "INSERT INTO traces(query_id,thread_id,payload,created_at) VALUES ($1,$2,$3,now())",
                query_id,
                thread_id,
                json.loads(json.dumps(payload, default=str)),
            )

    async def list_traces(self, limit: int) -> list[dict[str, Any]]:
        async with self.pool.acquire() as c:
            rows = await c.fetch("SELECT payload FROM traces ORDER BY id DESC LIMIT $1", limit)
        return [r["payload"] for r in rows]

    async def purge_traces(self, older_than_days: int) -> int:
        async with self.pool.acquire() as c:
            r = await c.execute(
                "DELETE FROM traces WHERE created_at < now() - make_interval(days => $1)",
                older_than_days,
            )
        return int(r.split()[-1])
