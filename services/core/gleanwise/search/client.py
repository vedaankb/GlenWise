# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Ved Buddaraju

"""SearXNG client: retries, locale, dedupe, engine-health warnings."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlencode, urlsplit

import httpx

from gleanwise.config import Settings
from gleanwise.egress.log import LOG
from gleanwise.errors import NoResults, SearchUnavailable
from gleanwise.models import FOCUS_TO_SEARXNG, Focus, Source
from gleanwise.util.text import canonicalize_url, domain_of, strip_tracking

log = logging.getLogger(__name__)


@dataclass
class SearchOutcome:
    results: list[Source]
    warnings: list[str] = field(default_factory=list)


def _lang(locale: str | None) -> str:
    if not locale:
        return "auto"
    return locale.replace("_", "-")[:5]


class SearchClient:
    def __init__(self, settings: Settings, client: httpx.AsyncClient | None = None) -> None:
        self.settings = settings
        # The search backend is operator-configured (often 127.0.0.1) → plain client, no SSRF guard.
        self._client = client or httpx.AsyncClient(
            timeout=httpx.Timeout(12.0, connect=3.0),
            trust_env=False,
            headers={"User-Agent": settings.user_agent},
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    async def _once(self, params: dict[str, Any]) -> dict[str, Any]:
        url = self.settings.searxng_url.rstrip("/") + "/search"
        try:
            resp = await self._client.get(url, params=params)
        except (httpx.ConnectError, httpx.ConnectTimeout) as exc:
            raise SearchUnavailable(
                f"Search engine is not reachable at {self.settings.searxng_url}.",
                hint="Start SearXNG, or run `gleanwise doctor` for step-by-step help.",
                detail=str(exc)[:200],
            ) from exc
        except httpx.HTTPError as exc:
            raise SearchUnavailable(
                "Search engine did not respond in time.", detail=str(exc)[:200]
            ) from exc
        if resp.status_code == 403:
            raise SearchUnavailable(
                "SearXNG refused the request (JSON output is disabled).",
                hint="In SearXNG settings.yml set `search.formats: [html, json]`, or use the bundled config.",
            )
        if resp.status_code >= 500 or resp.status_code == 429:
            raise SearchUnavailable(f"Search engine returned HTTP {resp.status_code}.")
        resp.raise_for_status()
        parts = urlsplit(self.settings.searxng_url)
        LOG.record(
            parts.hostname or "searxng",
            parts.port or (443 if parts.scheme == "https" else 80),
            purpose="search",
            bytes_in=len(resp.content),
            detail="searxng",
        )
        data = resp.json()
        return data if isinstance(data, dict) else {}

    async def search(
        self,
        query: str,
        *,
        focus: Focus = Focus.general,
        limit: int = 10,
        locale: str | None = None,
    ) -> SearchOutcome:
        params: dict[str, Any] = {
            "q": query,
            "format": "json",
            "categories": FOCUS_TO_SEARXNG[focus],
            "language": _lang(locale or self.settings.locale or None),
            "safesearch": 1,
        }
        if focus == Focus.news:
            params["time_range"] = "month"
        data: dict[str, Any] = {}
        for attempt in range(3):
            try:
                data = await self._once(params)
                break
            except SearchUnavailable:
                if attempt == 2:
                    raise
                await asyncio.sleep(0.4 * (2**attempt))
        seen: dict[str, Source] = {}
        for item in data.get("results", []):
            url = str(item.get("url") or "")
            if not url.startswith(("http://", "https://")):
                continue
            key = canonicalize_url(url)
            if key in seen:
                existing = seen[key]
                for e in item.get("engines", []) or []:
                    if e not in existing.engines:
                        existing.engines.append(e)
                continue
            seen[key] = Source(
                id=len(seen) + 1,
                url=strip_tracking(url),
                title=str(item.get("title") or domain_of(url))[:300],
                snippet=str(item.get("content") or "")[:800],
                domain=domain_of(url),
                favicon=f"/proxy/favicon?domain={domain_of(url)}",
                published_at=(
                    str(item.get("publishedDate")) if item.get("publishedDate") else None
                ),
                engines=list(item.get("engines") or [])[:6],
            )
            if len(seen) >= limit:
                break
        warnings = [
            f"{name} did not respond ({reason})"
            for name, reason in (data.get("unresponsive_engines") or [])
        ]
        if not seen:
            blocked = bool(warnings)
            raise NoResults(
                "No results found for that search.",
                hint=(
                    "Some search engines are temporarily blocking this server; try again in a minute."
                    if blocked
                    else "Try different keywords or another focus."
                ),
                action="retry" if blocked else None,
            )
        return SearchOutcome(results=list(seen.values()), warnings=warnings)

    async def ping(self) -> tuple[bool, str]:
        try:
            resp = await self._client.get(
                self.settings.searxng_url.rstrip("/")
                + "/search?"
                + urlencode({"q": "test", "format": "json"}),
                timeout=6.0,
            )
        except httpx.HTTPError as exc:
            return False, f"unreachable ({type(exc).__name__})"
        if resp.status_code == 403:
            return False, "JSON format disabled"
        return resp.status_code < 400, f"HTTP {resp.status_code}"
