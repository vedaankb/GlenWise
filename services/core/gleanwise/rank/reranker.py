# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Ved Buddaraju

"""Rerankers: real cross-encoder (fastembed/ONNX) with a lexical fallback that is *reported*."""

from __future__ import annotations

import asyncio
import logging
import math
import threading
from collections import Counter
from typing import Any, Protocol

from gleanwise.config import Settings
from gleanwise.util.text import tokens

log = logging.getLogger(__name__)


class Reranker(Protocol):
    name: str
    degraded_reason: str | None

    async def score(self, query: str, passages: list[str]) -> list[float]: ...
    async def warm(self) -> None: ...
    @property
    def loaded(self) -> bool: ...


class LexicalReranker:
    """Query-term coverage weighted by IDF over the candidate set. Cheap, deterministic."""

    name = "lexical"

    def __init__(self, degraded_reason: str | None = None) -> None:
        self.degraded_reason = degraded_reason

    @property
    def loaded(self) -> bool:
        return True

    async def warm(self) -> None:
        return None

    async def score(self, query: str, passages: list[str]) -> list[float]:
        q = set(tokens(query))
        if not q or not passages:
            return [0.0] * len(passages)
        docs = [Counter(tokens(p)) for p in passages]
        n = len(docs)
        idf = {
            t: math.log(
                1
                + (n - sum(1 for d in docs if t in d) + 0.5)
                / (sum(1 for d in docs if t in d) + 0.5)
            )
            for t in q
        }
        total = sum(idf.values()) or 1.0
        out: list[float] = []
        for d in docs:
            length = sum(d.values()) or 1
            cov = sum(idf[t] for t in q if t in d) / total
            density = sum(d[t] for t in q) / length
            out.append(cov + 0.25 * min(1.0, density * 10))
        return out


_CE: dict[str, Any] = {}
_CE_LOCK = threading.Lock()


class CrossEncoderReranker:
    def __init__(self, settings: Settings) -> None:
        self.model_name = settings.effective_reranker_model()
        self.name = self.model_name
        self._cache = str(settings.resolved_data_dir() / "models")
        self._offline = settings.offline
        self.degraded_reason: str | None = None
        self._fallback = LexicalReranker()

    @property
    def loaded(self) -> bool:
        return self.model_name in _CE

    def _model(self) -> Any:
        with _CE_LOCK:
            model = _CE.get(self.model_name)
            if model is None:
                from fastembed.rerank.cross_encoder import TextCrossEncoder

                model = TextCrossEncoder(
                    model_name=self.model_name,
                    cache_dir=self._cache,
                    local_files_only=self._offline,
                )
                _CE[self.model_name] = model
            return model

    async def warm(self) -> None:
        try:
            await asyncio.to_thread(self._model)
        except Exception as exc:
            self.degraded_reason = (
                f"cross-encoder unavailable ({type(exc).__name__}); using lexical ranking"
            )
            log.warning(self.degraded_reason)

    def _score(self, query: str, passages: list[str]) -> list[float]:
        return [float(s) for s in self._model().rerank(query, passages, batch_size=16)]

    async def score(self, query: str, passages: list[str]) -> list[float]:
        if not passages:
            return []
        if self.degraded_reason:
            return await self._fallback.score(query, passages)
        try:
            return await asyncio.to_thread(self._score, query, passages)
        except Exception as exc:
            self.degraded_reason = (
                f"cross-encoder failed ({type(exc).__name__}); using lexical ranking"
            )
            log.warning(self.degraded_reason)
            return await self._fallback.score(query, passages)


def build_reranker(settings: Settings) -> Reranker:
    if settings.reranker == "lexical":
        return LexicalReranker()
    return CrossEncoderReranker(settings)
