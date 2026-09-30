# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Ved Buddaraju

"""SSRF defences.

Two layers, both mandatory for every outbound fetch on behalf of a user or a web page:

1. ``validate_url`` — cheap syntactic checks (scheme, credentials, port, literal IPs).
2. ``resolve_public`` — resolves the host *and* verifies that every returned address is globally
   routable.  The HTTP transport (see ``fetch/http.py``) connects to exactly the addresses this
   function returns, so there is no window for DNS rebinding between "check" and "use".
"""

from __future__ import annotations

import asyncio
import ipaddress
import socket
from urllib.parse import urlsplit

from gleanwise.errors import FetchBlocked

_ALLOWED_LOW_PORTS = {80, 443}
_BLOCKED_SUFFIXES = (".local", ".localhost", ".internal", ".lan", ".home.arpa", ".intranet")
_BLOCKED_NAMES = {"localhost", "metadata.google.internal", "metadata"}

IPAddress = ipaddress.IPv4Address | ipaddress.IPv6Address


def _unwrap(ip: IPAddress) -> IPAddress:
    """Return the embedded IPv4 for IPv4-mapped / 6to4 / Teredo IPv6 forms."""
    if isinstance(ip, ipaddress.IPv6Address):
        if ip.ipv4_mapped is not None:
            return ip.ipv4_mapped
        if ip.sixtofour is not None:
            return ip.sixtofour
        if ip.teredo is not None:
            return ip.teredo[1]
    return ip


def is_public_ip(ip: IPAddress) -> bool:
    inner = _unwrap(ip)
    return bool(inner.is_global and not inner.is_multicast and not ip.is_multicast)


def _literal_ip(host: str) -> IPAddress | None:
    try:
        return ipaddress.ip_address(host.strip("[]"))
    except ValueError:
        return None


def validate_url(url: str, *, allow_private: bool = False) -> str:
    """Return the URL if syntactically acceptable, else raise ``FetchBlocked``."""
    if not url or len(url) > 4000:
        raise FetchBlocked("URL is empty or too long.")
    try:
        parts = urlsplit(url.strip())
        port = parts.port
    except ValueError as exc:
        raise FetchBlocked("URL is malformed.") from exc
    if parts.scheme not in {"http", "https"}:
        raise FetchBlocked("Only http and https URLs can be fetched.")
    if parts.username or parts.password:
        raise FetchBlocked("URLs with embedded credentials are not allowed.")
    host = (parts.hostname or "").lower().rstrip(".")
    if not host:
        raise FetchBlocked("URL has no host.")
    if allow_private:
        return url.strip()
    if port is not None and port not in _ALLOWED_LOW_PORTS and port < 1024:
        raise FetchBlocked("Port is not allowed.")
    if host in _BLOCKED_NAMES or host.endswith(_BLOCKED_SUFFIXES):
        raise FetchBlocked("Internal hostnames are not allowed.")
    literal = _literal_ip(host)
    if literal is not None and not is_public_ip(literal):
        raise FetchBlocked("Private or reserved addresses are not allowed.")
    return url.strip()


async def resolve_public(host: str, port: int, *, allow_private: bool = False) -> list[str]:
    """Resolve ``host`` and return addresses to connect to; all must be public."""
    host = host.strip("[]")
    literal = _literal_ip(host)
    if literal is not None:
        if not allow_private and not is_public_ip(literal):
            raise FetchBlocked("Private or reserved addresses are not allowed.")
        return [str(literal)]
    loop = asyncio.get_running_loop()
    try:
        infos = await loop.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise FetchBlocked(f"Could not resolve host '{host}'.") from exc
    addrs: list[str] = []
    for _fam, _typ, _proto, _canon, sockaddr in infos:
        raw = str(sockaddr[0]).split("%", 1)[0]
        ip = ipaddress.ip_address(raw)
        if not allow_private and not is_public_ip(ip):
            # One bad answer poisons the whole set: refuse rather than "pick the good one".
            raise FetchBlocked("Host resolves to a private or reserved address.")
        if raw not in addrs:
            addrs.append(raw)
    if not addrs:
        raise FetchBlocked(f"Host '{host}' has no addresses.")
    return addrs
