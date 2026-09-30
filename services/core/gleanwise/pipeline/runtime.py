# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Ved Buddaraju

"""Query lifecycle: bounded concurrency, replayable event log, cancellation, orphan cleanup."""

from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel

from gleanwise.errors import Busy, NotFound
from gleanwise.models import QueryRequest, QueryStatus
from gleanwise.services import Services
from gleanwise.telemetry import metrics

log = logging.getLogger(__name__)

TERMINAL = {"done", "error"}
RETAIN_S = 15 * 60
ORPHAN_GRACE_S = 20.0


@dataclass
class Event:
    id: int
    name: str
    data: str


@dataclass
class Job:
    query_id: str
    thread_id: str
    request: QueryRequest
    created: float = field(default_factory=time.monotonic)
    events: list[Event] = field(default_factory=list)
    status: str = "queued"
    finished_at: float | None = None
    subscribers: int = 0
    cancel_requested: bool = False
    task: asyncio.Task[Any] | None = None
    _waiters: list[asyncio.Future[None]] = field(default_factory=list)
    final: dict[str, Any] | None = None  # the terminal event payload

    def emit(self, name: str, payload: BaseModel | dict[str, Any]) -> None:
        data = payload.model_dump(mode="json") if isinstance(payload, BaseModel) else payload
        self.events.append(
            Event(id=len(self.events) + 1, name=name, data=json.dumps(data, ensure_ascii=False))
        )
        if name in TERMINAL:
            self.finished_at = time.monotonic()
            self.final = data
        self._wake()

    def _wake(self) -> None:
        for fut in self._waiters:
            if not fut.done():
                fut.set_result(None)
        self._waiters.clear()

    @property
    def finished(self) -> bool:
        return self.finished_at is not None

    async def stream(self, after: int = 0) -> AsyncIterator[Event]:
        """Yield events with id > ``after`` (replaying history), then live ones, ending at done/error."""
        idx = max(0, after)
        loop = asyncio.get_running_loop()
        while True:
            while idx < len(self.events):
                ev = self.events[idx]
                idx += 1
                yield ev
                if ev.name in TERMINAL:
                    return
            if self.finished:
                return
            fut: asyncio.Future[None] = loop.create_future()
            self._waiters.append(fut)
            await fut

    async def wait(self) -> dict[str, Any]:
        async for _ in self.stream(0):
            pass
        return self.final or {}

    def snapshot(self) -> QueryStatus:
        status = self.status
        return QueryStatus(
            query_id=self.query_id,
            thread_id=self.thread_id,
            status=status,  # type: ignore[arg-type]
            mode=self.request.mode,
            last_event_id=len(self.events),
        )


class QueryRuntime:
    def __init__(self, svc: Services) -> None:
        self.svc = svc
        self.jobs: dict[str, Job] = {}
        self._sem = asyncio.Semaphore(svc.settings.max_concurrent_queries)
        self._waiting = 0
        self._running = 0

    # -- submit / lookup -----------------------------------------------------------------------
    async def submit(self, req: QueryRequest) -> Job:
        s = self.svc.settings
        if len(req.query) > s.max_query_chars:
            from gleanwise.errors import BadRequest

            raise BadRequest(
                f"Question is too long (max {s.max_query_chars} characters).",
                action="shorten_query",
            )
        self._evict()
        if self._running + self._waiting >= s.max_concurrent_queries + s.max_queued_queries:
            raise Busy(
                "The server is busy with other questions.", hint="Try again in a few seconds."
            )

        # Private queries never touch the store (D6), even if persist was left true.
        if req.private:
            req = req.model_copy(update={"persist": False})
        thread_id: str
        if req.persist:
            if req.thread_id:
                if await self.svc.store.get_thread(req.thread_id) is None:
                    raise NotFound("That conversation no longer exists.")
                thread_id = req.thread_id
            else:
                title = " ".join(req.query.split())[:80]
                thread_id = (await self.svc.store.create_thread(title)).id
        else:
            thread_id = "ephemeral"
        job = Job(query_id=uuid.uuid4().hex, thread_id=thread_id, request=req)
        self.jobs[job.query_id] = job
        from gleanwise.pipeline.runner import execute

        job.task = self.svc.spawn(execute(self, job), f"query-{job.query_id[:8]}")
        self.svc.spawn(self._orphan_watch(job, ORPHAN_GRACE_S), f"orphan-{job.query_id[:8]}")
        return job

    def get(self, query_id: str) -> Job:
        job = self.jobs.get(query_id)
        if job is None:
            raise NotFound("That query is unknown or has expired.")
        return job

    def cancel(self, query_id: str) -> bool:
        job = self.jobs.get(query_id)
        if job is None or job.finished:
            return False
        job.cancel_requested = True
        if job.task and not job.task.done():
            job.task.cancel()
        return True

    # -- concurrency slot ---------------------------------------------------------------------
    async def acquire(self, job: Job) -> None:
        self._waiting += 1
        metrics.QUEUED.set(self._waiting)
        try:
            await self._sem.acquire()
        finally:
            self._waiting -= 1
            metrics.QUEUED.set(self._waiting)
        self._running += 1
        metrics.ACTIVE.set(self._running)
        job.status = "running"

    def release(self) -> None:
        self._sem.release()
        self._running -= 1
        metrics.ACTIVE.set(self._running)

    # -- housekeeping ---------------------------------------------------------------------------
    def _evict(self) -> None:
        now = time.monotonic()
        for qid in [
            q for q, j in self.jobs.items() if j.finished_at and now - j.finished_at > RETAIN_S
        ]:
            self.jobs.pop(qid, None)

    async def _orphan_watch(self, job: Job, grace: float) -> None:
        """Cancel work nobody is listening to (browser closed / navigated away)."""
        await asyncio.sleep(grace)
        while not job.finished:
            if job.subscribers == 0:
                log.info("cancelling orphaned query %s", job.query_id)
                self.cancel(job.query_id)
                return
            await asyncio.sleep(5)

    async def subscribe(self, job: Job, after: int = 0) -> AsyncIterator[Event]:
        job.subscribers += 1
        try:
            async for ev in job.stream(after):
                yield ev
        finally:
            job.subscribers -= 1
            if job.subscribers == 0 and not job.finished:
                self.svc.spawn(
                    self._orphan_watch(job, ORPHAN_GRACE_S), f"orphan-{job.query_id[:8]}"
                )
