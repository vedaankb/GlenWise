# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Ved Buddaraju

"""Shared headless-browser pool for JS-heavy pages (optional; degrades to a no-op).

Ephemeral context per fetch (no cookies / storage), tracker host blocking (D10), optional
egress-gateway proxy (D3).
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from typing import TYPE_CHECKING, Any
from urllib.parse import urlsplit

from gleanwise.egress.log import LOG
from gleanwise.errors import FetchBlocked
from gleanwise.fetch.trackers import is_tracker_url
from gleanwise.security.ssrf import resolve_public, validate_url

if TYPE_CHECKING:
    from gleanwise.config import Settings

log = logging.getLogger(__name__)


class BrowserPool:
    def __init__(
        self,
        *,
        allow_private: bool = False,
        concurrency: int = 2,
        timeout_s: float = 15.0,
        settings: Settings | None = None,
        proxy_url: str | None = None,
    ) -> None:
        self._allow_private = allow_private
        self._sem = asyncio.Semaphore(concurrency)
        self._timeout = timeout_s
        self.settings = settings
        self._proxy = proxy_url
        self._pw: Any = None
        self._browser: Any = None
        self._lock = asyncio.Lock()
        self.available: bool | None = None  # None = not yet probed

    async def _ensure(self) -> bool:
        if self.available is not None:
            return self.available
        async with self._lock:
            if self.available is not None:
                return self.available
            try:
                from playwright.async_api import async_playwright

                self._pw = await async_playwright().start()
                launch_args: dict[str, Any] = {"headless": True}
                # Chromium talks to the world through our gateway when one is configured.
                if self._proxy:
                    launch_args["proxy"] = {"server": self._proxy}
                self._browser = await self._pw.chromium.launch(**launch_args)
                self.available = True
            except Exception as exc:
                log.info("browser fallback disabled: %s", str(exc).splitlines()[0][:120])
                self.available = False
        return self.available

    async def render(self, url: str) -> str | None:
        """Return rendered HTML, or None if the browser is unavailable or the load failed."""
        if not await self._ensure():
            return None
        validate_url(url, allow_private=self._allow_private)
        host = urlsplit(url).hostname or ""
        port = urlsplit(url).port or (443 if url.startswith("https") else 80)
        async with self._sem:
            context = await self._browser.new_context(
                java_script_enabled=True,
                accept_downloads=False,
                service_workers="block",
                bypass_csp=False,
                # No cookies, no storage — ephemeral per page (D10).
            )
            try:
                page = await context.new_page()

                async def guard(route: Any) -> None:
                    req_url: str = route.request.url
                    try:
                        if req_url.startswith(("data:", "blob:", "about:")):
                            await route.continue_()
                            return
                        if is_tracker_url(req_url):
                            await route.abort()
                            return
                        validate_url(req_url, allow_private=self._allow_private)
                        parts = urlsplit(req_url)
                        await resolve_public(
                            parts.hostname or "",
                            parts.port or (443 if parts.scheme == "https" else 80),
                            allow_private=self._allow_private,
                        )
                        if route.request.resource_type in {"image", "media", "font"}:
                            await route.abort()
                            return
                        await route.continue_()
                    except FetchBlocked:
                        await route.abort()

                await page.route("**/*", guard)
                await page.goto(
                    url, wait_until="domcontentloaded", timeout=int(self._timeout * 1000)
                )
                with contextlib.suppress(Exception):
                    await page.wait_for_load_state("networkidle", timeout=4000)
                html: str = await page.content()
                LOG.record(host, port, purpose="fetch", status="ok", detail="browser")
                return html
            except Exception as exc:
                log.debug("browser render failed for %s: %s", url, exc)
                LOG.record(host, port, purpose="fetch", status="error", detail=str(exc)[:120])
                return None
            finally:
                await context.close()

    async def aclose(self) -> None:
        with contextlib.suppress(Exception):
            if self._browser:
                await self._browser.close()
            if self._pw:
                await self._pw.stop()
        self._browser = self._pw = None
        self.available = None
