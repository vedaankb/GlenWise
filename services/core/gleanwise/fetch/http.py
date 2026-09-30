# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Ved Buddaraju

"""Hardened HTTP client for fetching untrusted URLs.

* connects only to addresses that passed ``resolve_public`` (IP pinning at the socket layer)
* follows redirects manually and re-validates every hop
* streams the body and stops at ``max_bytes`` of *decoded* data (defeats zip bombs)
* never reads proxy environment variables (a proxy would bypass the pin)
"""

from __future__ import annotations

import asyncio
import ssl
from collections import OrderedDict
from collections.abc import Iterable
from dataclasses import dataclass, field
from urllib.parse import urljoin, urlsplit

import httpcore
import httpx

from gleanwise.config import Settings
from gleanwise.errors import FetchBlocked, FetchFailed
from gleanwise.security.ssrf import resolve_public, validate_url

_REDIRECTS = {301, 302, 303, 307, 308}


class _GuardedBackend(httpcore.AsyncNetworkBackend):
    def __init__(self, allow_private: bool) -> None:
        self._inner = httpcore.AnyIOBackend()
        self._allow_private = allow_private

    async def connect_tcp(  # type: ignore[no-untyped-def]
        self, host, port, timeout=None, local_address=None, socket_options=None
    ):
        addrs = await resolve_public(host, port, allow_private=self._allow_private)
        last: Exception | None = None
        for addr in addrs:
            try:
                return await self._inner.connect_tcp(
                    addr,
                    port,
                    timeout=timeout,
                    local_address=local_address,
                    socket_options=socket_options,
                )
            except Exception as exc:  # try the next address
                last = exc
        assert last is not None
        raise last

    async def connect_unix_socket(self, path, timeout=None, socket_options=None):  # type: ignore[no-untyped-def]
        raise FetchBlocked("Unix sockets are not allowed.")

    async def sleep(self, seconds: float) -> None:
        await self._inner.sleep(seconds)


@dataclass
class HttpResult:
    url: str
    final_url: str
    status: int
    headers: dict[str, str]
    body: bytes = b""
    truncated: bool = False
    redirects: list[str] = field(default_factory=list)

    @property
    def content_type(self) -> str:
        return self.headers.get("content-type", "").split(";")[0].strip().lower()

    @property
    def declared_charset(self) -> str | None:
        ctype = self.headers.get("content-type", "")
        if "charset=" in ctype:
            return ctype.split("charset=", 1)[1].split(";")[0].strip().strip('"') or None
        return None


class SafeHTTP:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._client: httpx.AsyncClient | None = None
        self._host_locks: OrderedDict[str, asyncio.Semaphore] = OrderedDict()

    # -- lifecycle ------------------------------------------------------------------------
    def _build(self) -> httpx.AsyncClient:
        transport = httpx.AsyncHTTPTransport(retries=0, http2=False)
        transport._pool = httpcore.AsyncConnectionPool(
            ssl_context=ssl.create_default_context(),
            max_connections=64,
            max_keepalive_connections=16,
            keepalive_expiry=20.0,
            http1=True,
            http2=False,
            network_backend=_GuardedBackend(self.settings.ssrf_allow_private),
        )
        return httpx.AsyncClient(
            transport=transport,
            follow_redirects=False,
            trust_env=False,
            timeout=httpx.Timeout(self.settings.fetch_timeout_s, connect=6.0),
            headers={"User-Agent": self.settings.user_agent, "Accept-Language": "en;q=0.8,*;q=0.5"},
        )

    @property
    def client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = self._build()
        return self._client

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    def _host_lock(self, host: str) -> asyncio.Semaphore:
        lock = self._host_locks.get(host)
        if lock is None:
            lock = asyncio.Semaphore(self.settings.fetch_per_host)
            self._host_locks[host] = lock
            while len(self._host_locks) > 256:
                self._host_locks.popitem(last=False)
        else:
            self._host_locks.move_to_end(host)
        return lock

    # -- API ------------------------------------------------------------------------------
    async def get(
        self,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        max_bytes: int | None = None,
        max_redirects: int = 5,
        accept_types: Iterable[str] | None = None,
        timeout: float | None = None,
    ) -> HttpResult:
        """GET with SSRF-safe redirects and a hard cap on decoded body size."""
        cap = max_bytes or self.settings.fetch_max_bytes
        current = validate_url(url, allow_private=self.settings.ssrf_allow_private)
        hops: list[str] = []
        accepted = tuple(accept_types) if accept_types else None
        for _ in range(max_redirects + 1):
            host = urlsplit(current).hostname or ""
            try:
                async with (
                    self._host_lock(host),
                    self.client.stream(
                        "GET",
                        current,
                        headers=headers,
                        timeout=timeout or self.settings.fetch_timeout_s,
                    ) as resp,
                ):
                    status = resp.status_code
                    hdrs = {k.lower(): v for k, v in resp.headers.items()}
                    if status in _REDIRECTS and (loc := hdrs.get("location")):
                        hops.append(current)
                        current = validate_url(
                            urljoin(current, loc), allow_private=self.settings.ssrf_allow_private
                        )
                        continue
                    result = HttpResult(
                        url=url, final_url=current, status=status, headers=hdrs, redirects=hops
                    )
                    if status == 304 or status >= 400:
                        return result
                    ctype = result.content_type
                    if accepted and ctype and not any(ctype.startswith(a) for a in accepted):
                        result.status = 415
                        return result
                    chunks: list[bytes] = []
                    size = 0
                    async for part in resp.aiter_bytes():
                        size += len(part)
                        if size > cap:
                            chunks.append(part[: max(0, len(part) - (size - cap))])
                            result.truncated = True
                            break
                        chunks.append(part)
                    result.body = b"".join(chunks)
                    return result
            except FetchBlocked:
                raise
            except httpx.TimeoutException as exc:
                raise FetchFailed("The page took too long to respond.") from exc
            except httpx.HTTPError as exc:
                raise FetchFailed(f"Could not fetch the page ({type(exc).__name__}).") from exc
        raise FetchFailed("Too many redirects.")
