# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Ved Buddaraju

"""Process-wide service container: built once, shared by every request, closed on shutdown."""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from gleanwise.config import Settings
from gleanwise.egress import EgressGateway
from gleanwise.egress.log import LOG
from gleanwise.embed.embedder import Embedder, build_embedder
from gleanwise.fetch.browser import BrowserPool
from gleanwise.fetch.fetcher import PageFetcher
from gleanwise.fetch.http import SafeHTTP
from gleanwise.index import Store, open_store
from gleanwise.llm.client import LLM
from gleanwise.privacy.keychain import load_secret
from gleanwise.rank.reranker import Reranker, build_reranker
from gleanwise.search.client import SearchClient
from gleanwise.search.process import SearXNGProcess

log = logging.getLogger(__name__)


class Services:
    def __init__(self, settings: Settings, store: Store | None = None) -> None:
        self.settings = settings
        self.store: Store = store or open_store(settings)
        self.http = SafeHTTP(settings)
        self.browser: BrowserPool | None = None
        self.fetcher: PageFetcher
        self.search = SearchClient(settings)
        self.embedder: Embedder = build_embedder(settings)
        self.reranker: Reranker = build_reranker(settings)
        self.llm = LLM(settings)
        self.searxng = SearXNGProcess(settings)
        self.gateway = EgressGateway(settings, LOG)
        self.activity = LOG
        self.started_at = time.time()
        self.warm: dict[str, str] = {"embedder": "idle", "reranker": "idle"}
        self._tasks: set[asyncio.Task[Any]] = set()
        self._build_fetcher()

    def _build_fetcher(self) -> None:
        self.browser = (
            BrowserPool(
                allow_private=self.settings.ssrf_allow_private,
                settings=self.settings,
                proxy_url=None,  # filled after gateway starts
            )
            if self.settings.browser_fallback
            else None
        )
        self.fetcher = PageFetcher(self.settings, self.http, self.store, self.browser)

    def spawn(self, coro: Any, name: str) -> asyncio.Task[Any]:
        """Create a background task that is referenced (so it can't be GC'd) and logged on failure."""
        task = asyncio.create_task(coro, name=name)
        self._tasks.add(task)

        def _done(t: asyncio.Task[Any]) -> None:
            self._tasks.discard(t)
            if not t.cancelled() and (exc := t.exception()):
                log.warning("background task %s failed: %r", name, exc)

        task.add_done_callback(_done)
        return task

    async def start(self) -> None:
        # Resolve keychain refs so LLM/embed see plaintext keys in memory only.
        if self.settings.llm_api_key.startswith("keychain:"):
            self.settings = self.settings.model_copy(
                update={"llm_api_key": load_secret(self.settings.llm_api_key)}
            )
            self.llm = LLM(self.settings)
        await self.store.init()
        await self.gateway.start()
        if self.browser is not None:
            self.browser._proxy = self.gateway.proxy_url
        self.searxng.proxy_url = (
            self.gateway.proxy_url_for("search") if self.settings.egress_gateway else None
        )
        await self.searxng.start()
        self.spawn(self._warm(), "warm-models")
        self.spawn(self._maintenance(), "maintenance")

    async def _warm(self) -> None:
        for label, obj in (("embedder", self.embedder), ("reranker", self.reranker)):
            self.warm[label] = "loading"
            try:
                await obj.warm()
                self.warm[label] = "degraded" if getattr(obj, "degraded_reason", None) else "ready"
            except Exception as exc:
                self.warm[label] = f"error: {type(exc).__name__}"
                log.warning("%s warm-up failed: %s", label, exc)

    async def _maintenance(self) -> None:
        while True:
            try:
                s = self.settings
                await self.store.purge_threads(s.thread_retention_days)
                await self.store.purge_traces(s.trace_retention_days)
            except Exception as exc:
                log.warning("maintenance failed: %r", exc)
            await asyncio.sleep(6 * 3600)

    async def apply_settings(self, settings: Settings) -> None:
        """Hot-apply changed settings without restarting (model, key, search URL, embedder)."""
        old = self.settings
        self.settings = settings
        self.llm = LLM(settings)
        self.search = SearchClient(settings)
        if (settings.embedder, settings.effective_embed_model()) != (
            old.embedder,
            old.effective_embed_model(),
        ):
            self.embedder = build_embedder(settings)
            self.warm["embedder"] = "idle"
            self.spawn(self._warm_embedder(), "warm-embedder")
        self.fetcher.settings = settings
        self.http.settings = settings
        self.gateway.settings = settings
        # Hot-toggle gateway without a process restart.
        if settings.egress_gateway and self.gateway.status != "listening":
            await self.gateway.start()
        elif not settings.egress_gateway and self.gateway.status == "listening":
            await self.gateway.stop()
        if self.browser is not None:
            self.browser.settings = settings
            self.browser._proxy = self.gateway.proxy_url if settings.egress_gateway else None

    async def _warm_embedder(self) -> None:
        self.warm["embedder"] = "loading"
        try:
            await self.embedder.warm()
            self.warm["embedder"] = "ready"
        except Exception as exc:
            self.warm["embedder"] = f"error: {type(exc).__name__}"

    async def close(self) -> None:
        for t in list(self._tasks):
            t.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
        await self.searxng.stop()
        await self.gateway.stop()
        if self.browser:
            await self.browser.aclose()
        await self.http.aclose()
        await self.search.aclose()
        await self.store.close()
