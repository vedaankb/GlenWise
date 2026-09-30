# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Ved Buddaraju

"""Local HTTP CONNECT egress gateway.

All GleanWise outbound traffic can be pointed here. The gateway:

* logs host / port / purpose / bytes (no TLS decryption — paths stay private)
* enforces Strict Local for ``llm`` / ``embed`` purposes
* optionally forwards through a SOCKS5 upstream (Tor or a user proxy)
* re-validates fetch targets against the SSRF pin rules
"""

from __future__ import annotations

import asyncio
import base64
import logging
import socket
from pathlib import Path
from typing import TYPE_CHECKING
from urllib.parse import urlsplit

from gleanwise.egress.log import LOG, EgressLog, Purpose
from gleanwise.egress.policy import is_local_host
from gleanwise.security.ssrf import resolve_public

if TYPE_CHECKING:
    from gleanwise.config import Settings

log = logging.getLogger(__name__)

_BUF = 65536
_PURPOSES = {"fetch", "search", "llm", "embed", "webhook", "model", "other"}


class EgressGateway:
    def __init__(self, settings: Settings, activity: EgressLog | None = None) -> None:
        self.settings = settings
        self.log = activity or LOG
        self._server: asyncio.AbstractServer | None = None
        self.host = "127.0.0.1"
        self.port = 0
        self.status = "stopped"

    @property
    def proxy_url(self) -> str | None:
        if not self._server or not self.port:
            return None
        return f"http://{self.host}:{self.port}"

    def proxy_url_for(self, purpose: str) -> str | None:
        """Proxy URL that tags its traffic with a purpose (``purpose-<name>`` as the proxy user)."""
        if not self._server or not self.port:
            return None
        return f"http://purpose-{purpose}:x@{self.host}:{self.port}"

    def _port_file(self) -> Path | None:
        try:
            d = self.settings.resolved_data_dir()
            d.mkdir(parents=True, exist_ok=True)
            return d / "egress.port"
        except Exception:
            return None

    async def start(self) -> None:
        if self._server or not self.settings.egress_gateway:
            return
        # Reuse the previous port so long-lived children (SearXNG) keep a valid proxy URL.
        pf = self._port_file()
        preferred = 0
        if pf and pf.exists():
            try:
                preferred = int(pf.read_text().strip())
            except ValueError:
                preferred = 0
        try:
            self._server = await asyncio.start_server(self._client, self.host, preferred)
        except OSError:
            self._server = await asyncio.start_server(self._client, self.host, 0)
        sock = self._server.sockets[0]
        self.port = sock.getsockname()[1]
        if pf:
            try:
                pf.write_text(str(self.port))
            except OSError:
                pass
        self.status = "listening"
        log.info("egress gateway on %s:%s", self.host, self.port)

    async def stop(self) -> None:
        if self._server:
            self._server.close()
            await self._server.wait_closed()
        self._server = None
        self.port = 0
        self.status = "stopped"

    async def _client(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        peer = writer.get_extra_info("peername")
        try:
            first = await asyncio.wait_for(reader.readline(), timeout=10)
            if not first:
                return
            line = first.decode("latin-1", errors="replace").strip()
            purpose: Purpose = "other"
            # Drain headers; honour Proxy-Purpose when a client sets it.
            while True:
                h = await asyncio.wait_for(reader.readline(), timeout=10)
                if h in (b"\r\n", b"\n", b""):
                    break
                try:
                    hk, _, hv = h.decode("latin-1", errors="replace").partition(":")
                    key = hk.strip().lower()
                    val = hv.strip().lower()
                    if key == "proxy-purpose" and val in _PURPOSES:
                        purpose = val  # type: ignore[assignment]
                    elif key == "proxy-authorization" and val.startswith("basic "):
                        user = base64.b64decode(hv.strip()[6:]).decode("latin-1").split(":")[0]
                        if user.startswith("purpose-") and user[8:] in _PURPOSES:
                            purpose = user[8:]  # type: ignore[assignment]
                except Exception:
                    pass
            if line.upper().startswith("CONNECT "):
                await self._connect(line, reader, writer, purpose)
            else:
                # Absolute-form HTTP (rare for us); reject to keep the surface small.
                writer.write(b"HTTP/1.1 501 Not Implemented\r\nConnection: close\r\n\r\n")
                await writer.drain()
        except Exception as exc:
            log.debug("gateway client error from %s: %s", peer, exc)
        finally:
            try:
                writer.close()
                await writer.wait_closed()
            except Exception:
                pass

    async def _connect(
        self,
        line: str,
        client_r: asyncio.StreamReader,
        client_w: asyncio.StreamWriter,
        purpose: Purpose,
    ) -> None:
        # CONNECT host:port HTTP/1.1
        try:
            target = line.split()[1]
        except IndexError:
            client_w.write(b"HTTP/1.1 400 Bad Request\r\n\r\n")
            return
        host, _, port_s = target.partition(":")
        port = int(port_s or "443")
        purpose = self._infer_purpose(host, purpose)

        # Strict Local: block non-local llm/embed destinations.
        if purpose in {"llm", "embed"} and self.settings.strict_local:
            if not is_local_host(host, self.settings.local_hosts):
                self.log.record(
                    host, port, purpose=purpose, status="blocked", detail="strict_local"
                )
                client_w.write(b"HTTP/1.1 403 Forbidden\r\nConnection: close\r\n\r\n")
                await client_w.drain()
                return

        # Fetch targets must pass SSRF rules (gateway is the pin point when used as proxy).
        if purpose == "fetch" and not is_local_host(host):
            try:
                await resolve_public(host, port, allow_private=self.settings.ssrf_allow_private)
            except Exception as exc:
                self.log.record(
                    host, port, purpose=purpose, status="blocked", detail=str(exc)[:120]
                )
                client_w.write(b"HTTP/1.1 403 Forbidden\r\nConnection: close\r\n\r\n")
                await client_w.drain()
                return

        try:
            remote_r, remote_w = await self._open_remote(host, port, purpose)
        except Exception as exc:
            self.log.record(host, port, purpose=purpose, status="error", detail=str(exc)[:120])
            client_w.write(b"HTTP/1.1 502 Bad Gateway\r\nConnection: close\r\n\r\n")
            await client_w.drain()
            return

        client_w.write(b"HTTP/1.1 200 Connection Established\r\n\r\n")
        await client_w.drain()
        self.log.record(host, port, purpose=purpose, status="ok", detail="connected")
        bytes_c2s = bytes_s2c = 0
        try:
            bytes_c2s, bytes_s2c = await asyncio.wait_for(
                self._pipe(client_r, client_w, remote_r, remote_w),
                timeout=120,
            )
            self.log.record(
                host, port, purpose=purpose, bytes_in=bytes_s2c, bytes_out=bytes_c2s, status="ok"
            )
        except Exception as exc:
            self.log.record(
                host,
                port,
                purpose=purpose,
                bytes_in=bytes_s2c,
                bytes_out=bytes_c2s,
                status="error",
                detail=str(exc)[:120],
            )
        finally:
            try:
                remote_w.close()
                await remote_w.wait_closed()
            except Exception:
                pass

    def _infer_purpose(self, host: str, hinted: Purpose) -> Purpose:
        if hinted != "other":
            return hinted
        # Heuristic from settings so LiteLLM / SearXNG traffic is classified without a custom header.
        llm_host = (
            urlsplit(self.settings.llm_api_base).hostname if self.settings.llm_api_base else ""
        )
        search_host = (
            urlsplit(self.settings.searxng_url).hostname if self.settings.searxng_url else ""
        )
        if llm_host and host.lower() == llm_host.lower():
            return "llm"
        if search_host and host.lower() == search_host.lower():
            return "search"
        return "fetch"

    async def _open_remote(
        self, host: str, port: int, purpose: Purpose
    ) -> tuple[asyncio.StreamReader, asyncio.StreamWriter]:
        socks = self.settings.socks5_url.strip()
        # SOCKS5 / Tor applies to search and page fetching only; model calls stay direct.
        use_socks = bool(socks) and (
            (purpose == "search" and self.settings.socks5_for_search)
            or (purpose == "fetch" and self.settings.socks5_for_fetch)
        )
        if use_socks:
            return await self._socks_connect(socks, host, port)
        return await asyncio.open_connection(host, port, family=socket.AF_UNSPEC)

    async def _socks_connect(
        self, socks_url: str, host: str, port: int
    ) -> tuple[asyncio.StreamReader, asyncio.StreamWriter]:
        try:
            from python_socks.async_.asyncio import Proxy
        except ImportError as exc:
            raise RuntimeError(
                "SOCKS5 routing needs the python-socks package (install gleanwise with its default deps)."
            ) from exc
        proxy = Proxy.from_url(socks_url)
        sock = await proxy.connect(dest_host=host, dest_port=port)
        return await asyncio.open_connection(sock=sock)

    async def _pipe(
        self,
        c_r: asyncio.StreamReader,
        c_w: asyncio.StreamWriter,
        s_r: asyncio.StreamReader,
        s_w: asyncio.StreamWriter,
    ) -> tuple[int, int]:
        c2s = s2c = 0

        async def one(src: asyncio.StreamReader, dst: asyncio.StreamWriter, which: str) -> None:
            nonlocal c2s, s2c
            try:
                while True:
                    data = await src.read(_BUF)
                    if not data:
                        break
                    dst.write(data)
                    await dst.drain()
                    if which == "c2s":
                        c2s += len(data)
                    else:
                        s2c += len(data)
            except Exception:
                pass
            finally:
                try:
                    dst.close()
                except Exception:
                    pass

        await asyncio.gather(one(c_r, s_w, "c2s"), one(s_r, c_w, "s2c"))
        return c2s, s2c
