# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Ved Buddaraju

"""Per-query state shared by pipeline stages."""

from __future__ import annotations

import time
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel

from gleanwise.llm.client import Usage
from gleanwise.models import Mode, QueryRequest, Source, Turn, WarningEvent
from gleanwise.services import Services
from gleanwise.telemetry import metrics
from gleanwise.util.text import canonicalize_url

Emit = Callable[[str, BaseModel | dict[str, Any]], None]


@dataclass
class RunContext:
    svc: Services
    req: QueryRequest
    query_id: str
    thread_id: str
    history: list[Turn]
    emit: Emit
    model: str
    deadline_s: float
    usage: Usage = field(default_factory=Usage)
    started: float = field(default_factory=time.monotonic)
    sources: dict[int, Source] = field(default_factory=dict)
    by_url: dict[str, int] = field(default_factory=dict)
    doc_source: dict[str, Source] = field(default_factory=dict)  # doc_id → Source
    stages: list[dict[str, Any]] = field(default_factory=list)
    research_log: list[dict[str, Any]] = field(default_factory=list)
    first_token_at: float | None = None
    warned: set[str] = field(default_factory=set)
    round: int | None = None

    @property
    def mode(self) -> Mode:
        return self.req.mode

    @property
    def settings(self):  # type: ignore[no-untyped-def]
        return self.svc.settings

    @property
    def locale(self) -> str | None:
        return self.req.locale or self.svc.settings.locale or None

    @property
    def ttl_class(self) -> str:
        return self.req.focus.value if self.req.focus.value in {"news", "social"} else "default"

    def time_left(self) -> float:
        return self.deadline_s - (time.monotonic() - self.started)

    def warn(self, code: str, message: str) -> None:
        if code in self.warned:
            return
        self.warned.add(code)
        self.emit("warning", WarningEvent(code=code, message=message))

    def register(self, items: list[Source]) -> list[Source]:
        """Add new sources (dedupe by canonical URL) and assign stable, increasing ids."""
        fresh: list[Source] = []
        for s in items:
            key = canonicalize_url(s.url)
            if key in self.by_url:
                continue
            s = s.model_copy(update={"id": len(self.sources) + 1})
            self.sources[s.id] = s
            self.by_url[key] = s.id
            fresh.append(s)
        return fresh

    def note_first_token(self) -> None:
        if self.first_token_at is None:
            self.first_token_at = time.monotonic()
            metrics.TTFT.labels(self.mode.value).observe(self.first_token_at - self.started)

    @asynccontextmanager
    async def stage(self, name: str, **detail: Any) -> AsyncIterator[dict[str, Any]]:
        rec: dict[str, Any] = {"stage": name, **detail}
        t0 = time.monotonic()
        try:
            yield rec
        except BaseException as exc:
            rec["error"] = type(exc).__name__
            raise
        finally:
            rec["ms"] = int((time.monotonic() - t0) * 1000)
            metrics.STAGE_SECONDS.labels(self.mode.value, name).observe(rec["ms"] / 1000)
            self.stages.append(rec)
