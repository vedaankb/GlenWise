# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Ved Buddaraju

"""SQLite backend: WAL, versioned migrations, FTS5 (BM25), sqlite-vec (dense) with numpy fallback."""

from __future__ import annotations

import asyncio
import functools
import json
import logging
import sqlite3
import threading
import uuid
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Concatenate, ParamSpec, TypeVar

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
from gleanwise.util.text import fts_query

log = logging.getLogger(__name__)

P = ParamSpec("P")
R = TypeVar("R")
S = TypeVar("S", bound="SQLiteStore")


def offload(fn: Callable[Concatenate[S, P], R]) -> Callable[Concatenate[S, P], Any]:
    """Run a synchronous store method on a worker thread under the connection lock."""

    @functools.wraps(fn)
    async def wrapper(self: S, *args: P.args, **kwargs: P.kwargs) -> R:
        return await asyncio.to_thread(lambda: self._locked(fn, self, *args, **kwargs))

    return wrapper


def _now() -> datetime:
    return datetime.now(UTC)


def _iso(dt: datetime | None) -> str | None:
    return dt.astimezone(UTC).isoformat() if dt else None


def _dt(value: str | None) -> datetime | None:
    if not value:
        return None
    dt = datetime.fromisoformat(value)
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


MIGRATIONS: list[str] = [
    # v1 ------------------------------------------------------------------------------------
    """
    CREATE TABLE documents (
      id TEXT PRIMARY KEY,
      url TEXT NOT NULL,
      canonical_url TEXT NOT NULL UNIQUE,
      title TEXT NOT NULL DEFAULT '',
      content_type TEXT NOT NULL DEFAULT 'text/html',
      etag TEXT, last_modified TEXT,
      fetched_at TEXT, expires_at TEXT,
      ttl_class TEXT NOT NULL DEFAULT 'default',
      text TEXT NOT NULL DEFAULT ''
    );
    CREATE INDEX documents_expires ON documents(expires_at);

    CREATE TABLE chunks (
      id TEXT PRIMARY KEY,
      doc_id TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
      url TEXT NOT NULL,
      heading_path TEXT NOT NULL DEFAULT '',
      text TEXT NOT NULL,
      start INTEGER NOT NULL DEFAULT 0,
      "end" INTEGER NOT NULL DEFAULT 0,
      embedding_model TEXT, dim INTEGER, embedding BLOB
    );
    CREATE INDEX chunks_doc ON chunks(doc_id);
    CREATE INDEX chunks_model ON chunks(embedding_model);

    CREATE VIRTUAL TABLE chunks_fts USING fts5(
      text, heading_path, content='chunks', content_rowid='rowid',
      tokenize='unicode61 remove_diacritics 2'
    );
    CREATE TRIGGER chunks_ai AFTER INSERT ON chunks BEGIN
      INSERT INTO chunks_fts(rowid, text, heading_path) VALUES (new.rowid, new.text, new.heading_path);
    END;
    CREATE TRIGGER chunks_ad AFTER DELETE ON chunks BEGIN
      INSERT INTO chunks_fts(chunks_fts, rowid, text, heading_path)
      VALUES ('delete', old.rowid, old.text, old.heading_path);
    END;
    CREATE TRIGGER chunks_au AFTER UPDATE OF text, heading_path ON chunks BEGIN
      INSERT INTO chunks_fts(chunks_fts, rowid, text, heading_path)
      VALUES ('delete', old.rowid, old.text, old.heading_path);
      INSERT INTO chunks_fts(rowid, text, heading_path) VALUES (new.rowid, new.text, new.heading_path);
    END;

    CREATE TABLE threads (
      id TEXT PRIMARY KEY,
      title TEXT NOT NULL,
      pinned INTEGER NOT NULL DEFAULT 0,
      created_at TEXT NOT NULL,
      updated_at TEXT NOT NULL
    );
    CREATE INDEX threads_updated ON threads(pinned DESC, updated_at DESC);

    CREATE TABLE messages (
      id TEXT PRIMARY KEY,
      thread_id TEXT NOT NULL REFERENCES threads(id) ON DELETE CASCADE,
      role TEXT NOT NULL,
      content TEXT NOT NULL,
      citations TEXT NOT NULL DEFAULT '[]',
      sources TEXT NOT NULL DEFAULT '[]',
      mode TEXT, focus TEXT, query_id TEXT,
      research_summary TEXT, research_log TEXT,
      follow_ups TEXT NOT NULL DEFAULT '[]',
      created_at TEXT NOT NULL
    );
    CREATE INDEX messages_thread ON messages(thread_id, created_at);

    CREATE TABLE feedback (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      query_id TEXT NOT NULL,
      thumb INTEGER NOT NULL,
      comment TEXT,
      created_at TEXT NOT NULL
    );
    CREATE INDEX feedback_query ON feedback(query_id);

    CREATE TABLE traces (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      query_id TEXT NOT NULL,
      thread_id TEXT,
      payload TEXT NOT NULL,
      created_at TEXT NOT NULL
    );
    CREATE INDEX traces_created ON traces(created_at);
    """,
]


class SQLiteStore:
    backend = "sqlite"

    def __init__(self, path: Path | str) -> None:
        self.path = str(path)
        self._conn: sqlite3.Connection | None = None
        self._lock = threading.RLock()
        self.vec_enabled = False

    # -- infrastructure -------------------------------------------------------------------
    def _locked(self, fn: Callable[..., R], *args: Any, **kwargs: Any) -> R:
        with self._lock:
            return fn(*args, **kwargs)

    @property
    def db(self) -> sqlite3.Connection:
        assert self._conn is not None, "store not initialised"
        return self._conn

    async def init(self) -> None:
        await asyncio.to_thread(self._init_sync)

    def _init_sync(self) -> None:
        with self._lock:
            if self._conn is not None:
                return
            conn = sqlite3.connect(self.path, check_same_thread=False, isolation_level=None)
            conn.row_factory = sqlite3.Row
            for pragma in (
                "journal_mode=WAL",
                "synchronous=NORMAL",
                "foreign_keys=ON",
                "busy_timeout=5000",
                "temp_store=MEMORY",
                "cache_size=-32000",
            ):
                conn.execute(f"PRAGMA {pragma}")
            try:
                import sqlite_vec

                conn.enable_load_extension(True)
                sqlite_vec.load(conn)
                conn.enable_load_extension(False)
                self.vec_enabled = True
            except Exception as exc:  # extension loading unavailable on some Python builds
                log.warning("sqlite-vec unavailable (%s); dense search falls back to numpy", exc)
            self._conn = conn
            self._migrate()
            if self.path != ":memory:":
                try:
                    Path(self.path).chmod(0o600)
                except OSError:
                    pass

    def _migrate(self) -> None:
        current = int(self.db.execute("PRAGMA user_version").fetchone()[0])
        # Pre-release (0.1) development databases have tables but user_version == 0.
        if (
            current == 0
            and self.db.execute("SELECT 1 FROM sqlite_master WHERE name='chunks'").fetchone()
        ):
            log.warning(
                "Found an unversioned 0.1 development database; resetting it to the 0.2 schema."
            )
            for tbl in (
                "chunks_fts",
                "chunks",
                "documents",
                "messages",
                "threads",
                "feedback",
                "traces",
            ):
                self.db.execute(f"DROP TABLE IF EXISTS {tbl}")
        for target, script in enumerate(MIGRATIONS, start=1):
            if target <= current:
                continue
            self.db.execute("BEGIN")
            try:
                for stmt in _split_script(script):
                    self.db.execute(stmt)
                self.db.execute(f"PRAGMA user_version = {target}")
                self.db.execute("COMMIT")
            except BaseException:
                self.db.execute("ROLLBACK")
                raise

    async def close(self) -> None:
        def _close() -> None:
            with self._lock:
                if self._conn is not None:
                    try:
                        self._conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
                    finally:
                        self._conn.close()
                        self._conn = None

        await asyncio.to_thread(_close)

    @offload
    def ping(self) -> dict[str, Any]:
        self.db.execute("SELECT 1").fetchone()
        version = self.db.execute("PRAGMA user_version").fetchone()[0]
        return {
            "backend": "sqlite",
            "schema": version,
            "vector_index": "sqlite-vec" if self.vec_enabled else "numpy",
        }

    @offload
    def stats(self) -> dict[str, int]:
        q = lambda t: int(self.db.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0])  # noqa: E731
        return {
            "documents": q("documents"),
            "chunks": q("chunks"),
            "threads": q("threads"),
            "messages": q("messages"),
        }

    # -- documents & chunks ---------------------------------------------------------------
    @staticmethod
    def _doc(row: sqlite3.Row) -> Document:
        return Document(
            id=row["id"],
            url=row["url"],
            canonical_url=row["canonical_url"],
            title=row["title"],
            content_type=row["content_type"],
            etag=row["etag"],
            last_modified=row["last_modified"],
            fetched_at=_dt(row["fetched_at"]),
            expires_at=_dt(row["expires_at"]),
            ttl_class=row["ttl_class"],
            text=row["text"],
        )

    @offload
    def get_document(self, canonical_url: str) -> Document | None:
        row = self.db.execute(
            "SELECT * FROM documents WHERE canonical_url = ?", (canonical_url,)
        ).fetchone()
        return self._doc(row) if row else None

    @offload
    def get_documents(self, doc_ids: list[str]) -> dict[str, Document]:
        if not doc_ids:
            return {}
        marks = ",".join("?" * len(doc_ids))
        rows = self.db.execute(f"SELECT * FROM documents WHERE id IN ({marks})", doc_ids).fetchall()
        return {r["id"]: self._doc(r) for r in rows}

    @offload
    def put_document(self, doc: Document) -> None:
        self.db.execute(
            """INSERT INTO documents(id,url,canonical_url,title,content_type,etag,last_modified,
                                     fetched_at,expires_at,ttl_class,text)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)
               ON CONFLICT(canonical_url) DO UPDATE SET
                 url=excluded.url, title=excluded.title, content_type=excluded.content_type,
                 etag=excluded.etag, last_modified=excluded.last_modified,
                 fetched_at=excluded.fetched_at, expires_at=excluded.expires_at,
                 ttl_class=excluded.ttl_class, text=excluded.text""",
            (
                doc.id,
                doc.url,
                doc.canonical_url,
                doc.title,
                doc.content_type,
                doc.etag,
                doc.last_modified,
                _iso(doc.fetched_at),
                _iso(doc.expires_at),
                doc.ttl_class,
                doc.text,
            ),
        )

    @offload
    def touch_document(self, doc_id: str, fetched_at: datetime, expires_at: datetime) -> None:
        self.db.execute(
            "UPDATE documents SET fetched_at=?, expires_at=? WHERE id=?",
            (_iso(fetched_at), _iso(expires_at), doc_id),
        )

    @offload
    def chunk_count(self, doc_id: str) -> int:
        return int(
            self.db.execute("SELECT COUNT(*) FROM chunks WHERE doc_id=?", (doc_id,)).fetchone()[0]
        )

    def _vec_tables(self) -> list[str]:
        return [
            r[0]
            for r in self.db.execute(
                "SELECT name FROM sqlite_master WHERE name LIKE 'chunks_vec_%' AND type='table'"
            )
        ]

    def _ensure_vec_table(self, dim: int) -> str | None:
        if not self.vec_enabled:
            return None
        name = f"chunks_vec_{int(dim)}"
        self.db.execute(
            f"CREATE VIRTUAL TABLE IF NOT EXISTS {name} USING vec0(embedding float[{int(dim)}] distance_metric=cosine)"
        )
        return name

    @offload
    def replace_chunks(self, doc_id: str, chunks: list[Chunk]) -> None:
        self.db.execute("BEGIN IMMEDIATE")
        try:
            old = [
                r[0] for r in self.db.execute("SELECT rowid FROM chunks WHERE doc_id=?", (doc_id,))
            ]
            if old and self.vec_enabled:
                for tbl in self._vec_tables():
                    self.db.executemany(f"DELETE FROM {tbl} WHERE rowid = ?", [(r,) for r in old])
            self.db.execute("DELETE FROM chunks WHERE doc_id=?", (doc_id,))
            self.db.executemany(
                """INSERT OR REPLACE INTO chunks(id,doc_id,url,heading_path,text,start,"end")
                   VALUES (?,?,?,?,?,?,?)""",
                [(c.id, c.doc_id, c.url, c.heading_path, c.text, c.start, c.end) for c in chunks],
            )
            self.db.execute("COMMIT")
        except BaseException:
            self.db.execute("ROLLBACK")
            raise

    @staticmethod
    def _chunk(row: sqlite3.Row, score: float | None = None) -> Chunk:
        return Chunk(
            id=row["id"],
            doc_id=row["doc_id"],
            url=row["url"],
            heading_path=row["heading_path"],
            text=row["text"],
            start=row["start"],
            end=row["end"],
            embedding_model=row["embedding_model"],
            dim=row["dim"],
            score=score,
        )

    @offload
    def lead_chunks(self, doc_ids: list[str], per_doc: int) -> list[Chunk]:
        if not doc_ids:
            return []
        marks = ",".join("?" * len(doc_ids))
        rows = self.db.execute(
            f"""SELECT id,doc_id,url,heading_path,text,start,"end",embedding_model,dim FROM (
                  SELECT *, ROW_NUMBER() OVER (PARTITION BY doc_id ORDER BY start) AS rn
                  FROM chunks WHERE doc_id IN ({marks})) WHERE rn <= ?""",
            [*doc_ids, per_doc],
        ).fetchall()
        return [self._chunk(r) for r in rows]

    @offload
    def chunks_needing_vectors(self, doc_ids: list[str], model: str) -> list[Chunk]:
        if not doc_ids:
            return []
        marks = ",".join("?" * len(doc_ids))
        rows = self.db.execute(
            f"""SELECT id,doc_id,url,heading_path,text,start,"end",embedding_model,dim FROM chunks
                WHERE doc_id IN ({marks}) AND (embedding IS NULL OR embedding_model IS NOT ?)""",
            [*doc_ids, model],
        ).fetchall()
        return [self._chunk(r) for r in rows]

    @offload
    def set_vectors(self, chunk_ids: list[str], vectors: np.ndarray, model: str) -> None:
        if not chunk_ids:
            return
        vectors = _normalize(np.asarray(vectors, dtype=np.float32))
        dim = int(vectors.shape[1])
        vec_table = self._ensure_vec_table(dim)
        self.db.execute("BEGIN IMMEDIATE")
        try:
            for cid, vec in zip(chunk_ids, vectors, strict=True):
                blob = vec.tobytes()
                row = self.db.execute("SELECT rowid FROM chunks WHERE id=?", (cid,)).fetchone()
                if row is None:
                    continue
                rowid = row[0]
                if self.vec_enabled:
                    for tbl in self._vec_tables():
                        self.db.execute(f"DELETE FROM {tbl} WHERE rowid = ?", (rowid,))
                self.db.execute(
                    "UPDATE chunks SET embedding=?, embedding_model=?, dim=? WHERE id=?",
                    (blob, model, dim, cid),
                )
                if vec_table:
                    self.db.execute(
                        f"INSERT INTO {vec_table}(rowid, embedding) VALUES (?, ?)", (rowid, blob)
                    )
            self.db.execute("COMMIT")
        except BaseException:
            self.db.execute("ROLLBACK")
            raise

    @offload
    def bm25(self, query: str, limit: int, doc_ids: list[str] | None) -> list[Scored]:
        match = fts_query(query)
        if not match:
            return []
        sql = (
            'SELECT c.id,c.doc_id,c.url,c.heading_path,c.text,c.start,c."end",c.embedding_model,c.dim,'
            " bm25(chunks_fts, 1.0, 0.4) AS s FROM chunks_fts JOIN chunks c ON c.rowid = chunks_fts.rowid"
            " WHERE chunks_fts MATCH ?"
        )
        args: list[Any] = [match]
        if doc_ids is not None:
            if not doc_ids:
                return []
            sql += f" AND c.doc_id IN ({','.join('?' * len(doc_ids))})"
            args += doc_ids
        sql += " ORDER BY s LIMIT ?"
        args.append(limit)
        try:
            rows = self.db.execute(sql, args).fetchall()
        except sqlite3.OperationalError as exc:  # malformed expression must never take a query down
            log.warning("fts query rejected (%s): %r", exc, match)
            return []
        return [(self._chunk(r, -float(r["s"])), -float(r["s"])) for r in rows]

    @offload
    def dense(
        self, vector: np.ndarray, limit: int, doc_ids: list[str] | None, model: str
    ) -> list[Scored]:
        q = _normalize(np.asarray(vector, dtype=np.float32).reshape(1, -1))[0]
        dim = int(q.shape[0])
        cols = 'c.id,c.doc_id,c.url,c.heading_path,c.text,c.start,c."end",c.embedding_model,c.dim'
        if doc_ids is None and self.vec_enabled and f"chunks_vec_{dim}" in self._vec_tables():
            rows = self.db.execute(
                f"""SELECT {cols}, v.distance AS d FROM chunks_vec_{dim} v
                    JOIN chunks c ON c.rowid = v.rowid
                    WHERE v.embedding MATCH ? AND k = ? AND c.embedding_model = ?
                    ORDER BY v.distance""",
                (q.tobytes(), limit * 2, model),
            ).fetchall()
            return [(self._chunk(r, 1.0 - float(r["d"])), 1.0 - float(r["d"])) for r in rows][
                :limit
            ]
        # Scoped search touches a few hundred rows at most → exact brute force is faster and exact.
        sql = f"SELECT {cols}, c.embedding AS e FROM chunks c WHERE c.embedding_model = ? AND c.dim = ?"
        args: list[Any] = [model, dim]
        if doc_ids is not None:
            if not doc_ids:
                return []
            sql += f" AND c.doc_id IN ({','.join('?' * len(doc_ids))})"
            args += doc_ids
        rows = self.db.execute(sql, args).fetchall()
        if not rows:
            return []
        mat = np.vstack([np.frombuffer(r["e"], dtype=np.float32) for r in rows])
        sims = mat @ q
        order = np.argsort(-sims)[:limit]
        return [(self._chunk(rows[i], float(sims[i])), float(sims[i])) for i in order]

    @offload
    def clear_index(self) -> None:
        self.db.execute("BEGIN IMMEDIATE")
        try:
            if self.vec_enabled:
                for tbl in self._vec_tables():
                    self.db.execute(f"DROP TABLE {tbl}")
            self.db.execute("DELETE FROM chunks")
            self.db.execute("DELETE FROM documents")
            self.db.execute("COMMIT")
        except BaseException:
            self.db.execute("ROLLBACK")
            raise

    # -- threads & messages ---------------------------------------------------------------
    @offload
    def create_thread(self, title: str) -> ThreadSummary:
        tid, now = uuid.uuid4().hex, _now()
        self.db.execute(
            "INSERT INTO threads(id,title,pinned,created_at,updated_at) VALUES (?,?,0,?,?)",
            (tid, title[:200] or "New thread", _iso(now), _iso(now)),
        )
        return ThreadSummary(
            id=tid, title=title[:200] or "New thread", created_at=now, updated_at=now
        )

    @staticmethod
    def _thread(row: sqlite3.Row) -> ThreadSummary:
        return ThreadSummary(
            id=row["id"],
            title=row["title"],
            pinned=bool(row["pinned"]),
            created_at=_dt(row["created_at"]) or _now(),
            updated_at=_dt(row["updated_at"]) or _now(),
            mode=Mode(row["mode"]) if "mode" in row.keys() and row["mode"] else None,  # noqa: SIM118
        )

    @staticmethod
    def _message(row: sqlite3.Row) -> MessageOut:
        return MessageOut(
            id=row["id"],
            thread_id=row["thread_id"],
            role=row["role"],
            content=row["content"],
            citations=[Citation(**c) for c in json.loads(row["citations"] or "[]")],
            sources=[Source(**s) for s in json.loads(row["sources"] or "[]")],
            mode=Mode(row["mode"]) if row["mode"] else None,
            focus=Focus(row["focus"]) if row["focus"] else None,
            created_at=_dt(row["created_at"]),
            query_id=row["query_id"],
            research_summary=row["research_summary"],
            research_log=json.loads(row["research_log"]) if row["research_log"] else None,
            follow_ups=json.loads(row["follow_ups"] or "[]"),
        )

    @offload
    def get_thread(self, thread_id: str) -> ThreadDetail | None:
        row = self.db.execute("SELECT * FROM threads WHERE id=?", (thread_id,)).fetchone()
        if row is None:
            return None
        msgs = self.db.execute(
            "SELECT * FROM messages WHERE thread_id=? ORDER BY created_at, rowid", (thread_id,)
        ).fetchall()
        t = self._thread(row)
        return ThreadDetail(
            id=t.id,
            title=t.title,
            pinned=t.pinned,
            created_at=t.created_at,
            updated_at=t.updated_at,
            messages=[self._message(m) for m in msgs],
        )

    @offload
    def list_threads(self, q: str | None, limit: int, offset: int) -> list[ThreadSummary]:
        sql = (
            "SELECT t.*, (SELECT m.mode FROM messages m WHERE m.thread_id=t.id AND m.role='assistant'"
            " ORDER BY m.created_at DESC LIMIT 1) AS mode FROM threads t"
            " WHERE EXISTS (SELECT 1 FROM messages m WHERE m.thread_id = t.id)"
        )
        args: list[Any] = []
        if q and q.strip():
            like = (
                "%" + q.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
            )
            sql += (
                " AND (t.title LIKE ? ESCAPE '\\' OR EXISTS (SELECT 1 FROM messages m WHERE m.thread_id=t.id"
                " AND m.content LIKE ? ESCAPE '\\'))"
            )
            args += [like, like]
        sql += " ORDER BY t.pinned DESC, t.updated_at DESC LIMIT ? OFFSET ?"
        args += [limit, offset]
        return [self._thread(r) for r in self.db.execute(sql, args).fetchall()]

    @offload
    def update_thread(self, thread_id: str, title: str | None, pinned: bool | None) -> bool:
        sets: list[str] = []
        args: list[Any] = []
        if title is not None:
            sets.append("title=?")
            args.append(title[:200])
        if pinned is not None:
            sets.append("pinned=?")
            args.append(1 if pinned else 0)
        if not sets:
            return (
                self.db.execute("SELECT 1 FROM threads WHERE id=?", (thread_id,)).fetchone()
                is not None
            )
        args.append(thread_id)
        cur = self.db.execute(f"UPDATE threads SET {', '.join(sets)} WHERE id=?", args)
        return cur.rowcount > 0

    @offload
    def delete_thread(self, thread_id: str) -> bool:
        return self.db.execute("DELETE FROM threads WHERE id=?", (thread_id,)).rowcount > 0

    @offload
    def add_turn(
        self, thread_id: str, user: dict[str, Any], assistant: dict[str, Any]
    ) -> MessageOut:
        now = _now()
        self.db.execute("BEGIN IMMEDIATE")
        try:
            uid, aid = uuid.uuid4().hex, uuid.uuid4().hex
            for mid, msg, offset in ((uid, user, 0), (aid, assistant, 1)):
                self.db.execute(
                    """INSERT INTO messages(id,thread_id,role,content,citations,sources,mode,focus,query_id,
                                            research_summary,research_log,follow_ups,created_at)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        mid,
                        thread_id,
                        msg["role"],
                        msg["content"],
                        json.dumps(msg.get("citations", [])),
                        json.dumps(msg.get("sources", [])),
                        msg.get("mode"),
                        msg.get("focus"),
                        msg.get("query_id"),
                        msg.get("research_summary"),
                        json.dumps(msg["research_log"]) if msg.get("research_log") else None,
                        json.dumps(msg.get("follow_ups", [])),
                        _iso(now + timedelta(microseconds=offset)),
                    ),
                )
            self.db.execute("UPDATE threads SET updated_at=? WHERE id=?", (_iso(now), thread_id))
            self.db.execute("COMMIT")
        except BaseException:
            self.db.execute("ROLLBACK")
            raise
        return self._message(
            self.db.execute("SELECT * FROM messages WHERE id=?", (aid,)).fetchone()
        )

    @offload
    def history(self, thread_id: str, limit: int) -> list[Turn]:
        rows = self.db.execute(
            "SELECT role, content FROM messages WHERE thread_id=? ORDER BY created_at DESC, rowid DESC LIMIT ?",
            (thread_id, limit),
        ).fetchall()
        return [Turn(role=r["role"], content=r["content"]) for r in reversed(rows)]

    @offload
    def delete_message(self, message_id: str) -> bool:
        """Delete a message; deleting an answer also removes the question it answered."""
        row = self.db.execute(
            "SELECT thread_id, role, created_at FROM messages WHERE id=?", (message_id,)
        ).fetchone()
        if row is None:
            return False
        if row["role"] == "assistant":
            prev = self.db.execute(
                "SELECT id FROM messages WHERE thread_id=? AND role='user' AND created_at <= ? ORDER BY created_at DESC LIMIT 1",
                (row["thread_id"], row["created_at"]),
            ).fetchone()
            if prev:
                self.db.execute("DELETE FROM messages WHERE id=?", (prev["id"],))
        return self.db.execute("DELETE FROM messages WHERE id=?", (message_id,)).rowcount > 0

    @offload
    def purge_threads(self, older_than_days: int) -> int:
        cutoff = _iso(_now() - timedelta(days=older_than_days))
        n = 0
        if older_than_days > 0:
            n += self.db.execute(
                "DELETE FROM threads WHERE pinned=0 AND updated_at < ?", (cutoff,)
            ).rowcount
        # Threads that never received an answer (failed/cancelled first turns) are noise after a day.
        day = _iso(_now() - timedelta(days=1))
        n += self.db.execute(
            "DELETE FROM threads WHERE updated_at < ? AND NOT EXISTS (SELECT 1 FROM messages m WHERE m.thread_id=threads.id)",
            (day,),
        ).rowcount
        return n

    @offload
    def wipe_user_data(self) -> None:
        for tbl in ("messages", "threads", "feedback", "traces"):
            self.db.execute(f"DELETE FROM {tbl}")
        self.db.execute("VACUUM")

    # -- feedback & traces ----------------------------------------------------------------
    @offload
    def add_feedback(self, query_id: str, thumb: int, comment: str | None) -> None:
        self.db.execute(
            "INSERT INTO feedback(query_id,thumb,comment,created_at) VALUES (?,?,?,?)",
            (query_id, thumb, comment, _iso(_now())),
        )

    @offload
    def list_feedback(self, limit: int) -> list[FeedbackOut]:
        rows = self.db.execute(
            "SELECT * FROM feedback ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
        return [
            FeedbackOut(
                query_id=r["query_id"],
                thumb=r["thumb"],
                comment=r["comment"],
                created_at=_dt(r["created_at"]) or _now(),
            )
            for r in rows
        ]

    @offload
    def add_trace(self, query_id: str, thread_id: str | None, payload: dict[str, Any]) -> None:
        self.db.execute(
            "INSERT INTO traces(query_id,thread_id,payload,created_at) VALUES (?,?,?,?)",
            (query_id, thread_id, json.dumps(payload, default=str), _iso(_now())),
        )

    @offload
    def list_traces(self, limit: int) -> list[dict[str, Any]]:
        rows = self.db.execute(
            "SELECT payload FROM traces ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
        return [json.loads(r["payload"]) for r in rows]

    @offload
    def purge_traces(self, older_than_days: int) -> int:
        cutoff = _iso(_now() - timedelta(days=older_than_days))
        return self.db.execute("DELETE FROM traces WHERE created_at < ?", (cutoff,)).rowcount


def _normalize(mat: np.ndarray) -> np.ndarray:
    norms = np.linalg.norm(mat, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    return (mat / norms).astype(np.float32)


def _split_script(script: str) -> list[str]:
    """Split a migration script into statements, keeping CREATE TRIGGER ... END; blocks whole."""
    stmts: list[str] = []
    buf: list[str] = []
    in_trigger = False
    for line in script.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("--"):
            continue
        buf.append(line)
        if stripped.upper().startswith("CREATE TRIGGER"):
            in_trigger = True
        if in_trigger:
            if stripped.upper() == "END;":
                stmts.append("\n".join(buf))
                buf, in_trigger = [], False
        elif stripped.endswith(";"):
            stmts.append("\n".join(buf))
            buf = []
    if buf:
        stmts.append("\n".join(buf))
    return stmts
