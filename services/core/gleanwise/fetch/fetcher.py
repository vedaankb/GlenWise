# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Ved Buddaraju

"""Page acquisition: cache → robots → conditional GET → parse → (optional) browser render."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from gleanwise.config import Settings
from gleanwise.egress.log import LOG
from gleanwise.errors import FetchBlocked, FetchFailed
from gleanwise.fetch.browser import BrowserPool
from gleanwise.fetch.http import SafeHTTP
from gleanwise.fetch.robots import RobotsCache
from gleanwise.index.base import Store
from gleanwise.models import Document
from gleanwise.parse.parser import ParsedPage, decode_body, parse_html, parse_pdf
from gleanwise.util.text import canonicalize_url, sha1_hex

log = logging.getLogger(__name__)

MIN_USEFUL_CHARS = 400
ACCEPT = ("text/html", "application/xhtml", "text/plain", "application/pdf")


@dataclass
class FetchedPage:
    doc: Document
    final_url: str
    from_cache: bool = False
    truncated: bool = False
    rendered: bool = False
    lang: str | None = None
    published_at: str | None = None


class PageFetcher:
    def __init__(
        self, settings: Settings, http: SafeHTTP, store: Store, browser: BrowserPool | None
    ) -> None:
        self.settings = settings
        self.http = http
        self.store = store
        self.browser = browser
        self.robots = RobotsCache(http, settings.user_agent)
        self._sem = asyncio.Semaphore(settings.fetch_concurrency)
        self._inflight: dict[str, asyncio.Future[FetchedPage]] = {}

    def _ttl(self, ttl_class: str) -> timedelta:
        secs = (
            self.settings.fetch_ttl_news_s
            if ttl_class in {"news", "social"}
            else self.settings.fetch_ttl_s
        )
        return timedelta(seconds=secs)

    async def fetch(
        self, url: str, *, ttl_class: str = "default", force: bool = False, cache: bool = True
    ) -> FetchedPage:
        """Fetch ``url`` (deduplicating concurrent requests for the same page)."""
        key = canonicalize_url(url)
        pending = self._inflight.get(key)
        if pending is not None:
            return await asyncio.shield(pending)
        fut: asyncio.Future[FetchedPage] = asyncio.get_running_loop().create_future()
        self._inflight[key] = fut
        try:
            result = await self._fetch(url, key, ttl_class, force, cache=cache)
            fut.set_result(result)
            return result
        except BaseException as exc:
            if not fut.done():
                fut.set_exception(exc)
                fut.exception()  # mark retrieved so asyncio does not log "never retrieved"
            raise
        finally:
            self._inflight.pop(key, None)

    async def _fetch(  # noqa: C901
        self, url: str, key: str, ttl_class: str, force: bool, *, cache: bool = True
    ) -> FetchedPage:
        now = datetime.now(UTC)
        cached = await self.store.get_document(key) if cache else None
        if cached and not force and cached.expires_at and cached.expires_at > now and cached.text:
            return FetchedPage(doc=cached, final_url=cached.url, from_cache=True)

        if self.settings.respect_robots and not await self.robots.allowed(url):
            raise FetchBlocked(
                "The site's robots.txt asks automated readers not to fetch this page."
            )

        headers: dict[str, str] = {}
        if cached and cached.text:
            if cached.etag:
                headers["If-None-Match"] = cached.etag
            if cached.last_modified:
                headers["If-Modified-Since"] = cached.last_modified

        async with self._sem:
            res = await self.http.get(url, headers=headers, accept_types=ACCEPT)
        from urllib.parse import urlsplit

        parts = urlsplit(res.final_url or url)
        LOG.record(
            parts.hostname or "",
            parts.port or (443 if (parts.scheme or "https") == "https" else 80),
            purpose="fetch",
            status="ok" if res.status < 400 else "error",
            detail=f"http {res.status}",
        )

        if res.status == 304 and cached:
            await self.store.touch_document(cached.id, now, now + self._ttl(ttl_class))
            cached.expires_at = now + self._ttl(ttl_class)
            return FetchedPage(doc=cached, final_url=res.final_url, from_cache=True)
        if res.status == 415:
            raise FetchFailed("This link is not a readable page (unsupported content type).")
        if res.status in {401, 402, 403, 451}:
            raise FetchBlocked(f"The site refused access (HTTP {res.status}).")
        if res.status >= 400:
            raise FetchFailed(f"The site returned HTTP {res.status}.")

        parsed = await asyncio.to_thread(
            self._parse, res.content_type, res.body, res.declared_charset, res.final_url
        )
        rendered = False
        if (
            self.browser is not None
            and res.content_type != "application/pdf"
            and len(parsed.text) < MIN_USEFUL_CHARS
        ):
            html = await self.browser.render(res.final_url)
            if html:
                better = await asyncio.to_thread(parse_html, html, res.final_url)
                if len(better.text) > len(parsed.text):
                    parsed, rendered = better, True
        if not parsed.text.strip():
            raise FetchFailed("No readable text could be extracted from this page.")

        doc = Document(
            id=sha1_hex(key, length=16),
            url=res.final_url,
            canonical_url=key,
            title=parsed.title,
            content_type=res.content_type or "text/html",
            etag=res.headers.get("etag"),
            last_modified=res.headers.get("last-modified"),
            fetched_at=now,
            expires_at=now + self._ttl(ttl_class),
            ttl_class=ttl_class,
            text=parsed.text,
        )
        unchanged = bool(cached and cached.text == parsed.text)
        if cache:
            await self.store.put_document(doc)
        return FetchedPage(
            doc=doc,
            final_url=res.final_url,
            truncated=res.truncated,
            rendered=rendered,
            lang=parsed.lang,
            published_at=parsed.published_at,
            from_cache=unchanged,
        )

    @staticmethod
    def _parse(content_type: str, body: bytes, charset: str | None, url: str) -> ParsedPage:
        if content_type == "application/pdf":
            return parse_pdf(body)
        text = decode_body(body, charset)
        if content_type == "text/plain":
            return ParsedPage(text=text.strip())
        return parse_html(text, url)
