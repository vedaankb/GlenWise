# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Ved Buddaraju

"""Egress activity log: every outbound host the gateway (or a direct client) talked to."""

from __future__ import annotations

import threading
import time
from collections import deque
from dataclasses import asdict, dataclass
from typing import Any, Literal

Purpose = Literal["fetch", "search", "llm", "embed", "webhook", "model", "other"]


@dataclass
class EgressEntry:
    ts: float
    host: str
    port: int
    purpose: Purpose
    bytes_in: int = 0
    bytes_out: int = 0
    status: str = "ok"  # ok | blocked | error
    detail: str = ""

    def as_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["ts"] = self.ts
        return d


class EgressLog:
    """Thread-safe ring buffer shared by the gateway and direct clients."""

    def __init__(self, capacity: int = 500) -> None:
        self._cap = capacity
        self._items: deque[EgressEntry] = deque(maxlen=capacity)
        self._lock = threading.Lock()

    def record(
        self,
        host: str,
        port: int,
        *,
        purpose: Purpose = "other",
        bytes_in: int = 0,
        bytes_out: int = 0,
        status: str = "ok",
        detail: str = "",
    ) -> None:
        entry = EgressEntry(
            ts=time.time(),
            host=host.lower(),
            port=port,
            purpose=purpose,
            bytes_in=bytes_in,
            bytes_out=bytes_out,
            status=status,
            detail=detail[:200],
        )
        with self._lock:
            self._items.append(entry)

    def recent(self, limit: int = 100) -> list[dict[str, Any]]:
        with self._lock:
            items = list(self._items)[-limit:]
        items.reverse()
        return [e.as_dict() for e in items]

    def clear(self) -> None:
        with self._lock:
            self._items.clear()


# Process-wide log; Services holds a reference too for tests that swap it.
LOG = EgressLog()
