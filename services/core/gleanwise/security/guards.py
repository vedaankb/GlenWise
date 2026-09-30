# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Ved Buddaraju

"""HTTP-level protections for a service that binds to localhost and is driven by browsers.

* **Host guard** – defeats DNS rebinding: a page on evil.example that re-points its DNS at
  127.0.0.1 still sends ``Host: evil.example``, which we refuse.
* **Origin guard** – defeats cross-site request forgery against state-changing endpoints.
* **Security headers** – nosniff, framing, referrer and (for HTML) a strict CSP.

Implemented as pure ASGI middleware so streaming (SSE) responses are never buffered.
"""

from __future__ import annotations

import ipaddress
import json
import socket
from collections.abc import Iterable
from urllib.parse import urlsplit

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from gleanwise.config import Settings

_MUTATING = {"POST", "PUT", "PATCH", "DELETE"}
LOOPBACK_NAMES = {"localhost", "127.0.0.1", "::1"}

CSP = (
    "default-src 'self'; img-src 'self' data: blob:; style-src 'self' 'unsafe-inline'; "
    "script-src 'self'; connect-src 'self'; font-src 'self' data:; "
    "manifest-src 'self'; worker-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
)


def _host_only(value: str) -> str:
    value = value.strip().lower()
    if value.startswith("["):
        return value[1 : value.find("]")] if "]" in value else value
    return value.rsplit(":", 1)[0] if value.count(":") == 1 else value


def _is_ip(host: str) -> bool:
    try:
        ipaddress.ip_address(host)
    except ValueError:
        return False
    return True


def allowed_host_names(settings: Settings) -> set[str]:
    names = set(LOOPBACK_NAMES)
    if settings.host not in {"0.0.0.0", "::", ""}:  # noqa: S104
        names.add(settings.host.lower())
    try:
        machine = socket.gethostname().lower()
        names.update({machine, machine.split(".")[0], f"{machine.split('.')[0]}.local"})
    except OSError:
        pass
    names.update(h.lower() for h in settings.allowed_hosts)
    return names


def effective_cors_origins(settings: Settings) -> list[str]:
    origins = list(settings.allowed_origins)
    if settings.profile == "local":
        origins += ["http://localhost:3000", "http://127.0.0.1:3000"]  # Next.js dev server
    return sorted(set(origins))


class SecurityGuard:
    def __init__(self, app: ASGIApp, settings: Settings) -> None:
        self.app = app
        self.names = allowed_host_names(settings)
        self.enforce_host = settings.profile == "local" or bool(settings.allowed_hosts)
        self.cors = set(effective_cors_origins(settings)) | set(settings.allowed_origins)

    def _host_ok(self, host: str) -> bool:
        if not self.enforce_host:
            return True
        name = _host_only(host)
        return bool(name) and (name in self.names or _is_ip(name) or name.endswith(".localhost"))

    def _origin_ok(self, origin: str | None, host: str) -> bool:
        if origin is None:
            return True  # not a browser cross-site request (curl, SDKs, server-to-server)
        if origin == "null":
            return False
        if origin in self.cors:
            return True
        try:
            return urlsplit(origin).netloc.lower() == host.strip().lower()
        except ValueError:
            return False

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] not in {"http", "websocket"}:
            await self.app(scope, receive, send)
            return
        headers = {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope["headers"]}
        host = headers.get("host", "")
        if not self._host_ok(host):
            await _reject(
                send,
                scope,
                421,
                "forbidden_host",
                "This host name is not allowed.",
                "Add it to GLEANWISE_ALLOWED_HOSTS if this is intentional.",
            )
            return
        if scope["type"] == "http" and scope["method"] in _MUTATING:
            if not self._origin_ok(headers.get("origin"), host):
                await _reject(
                    send,
                    scope,
                    403,
                    "forbidden_origin",
                    "Cross-origin request blocked.",
                    "Add the site to GLEANWISE_ALLOWED_ORIGINS to allow it.",
                )
                return
        await self.app(scope, receive, send)


class SecurityHeaders:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def wrapped(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers: list[tuple[bytes, bytes]] = list(message.get("headers", []))
                have = {k.lower() for k, _ in headers}
                extra: dict[bytes, bytes] = {
                    b"x-content-type-options": b"nosniff",
                    b"referrer-policy": b"no-referrer",
                    b"permissions-policy": b"camera=(), microphone=(), geolocation=(), interest-cohort=()",
                    b"cross-origin-opener-policy": b"same-origin",
                }
                ctype = next((v for k, v in headers if k.lower() == b"content-type"), b"")
                if ctype.startswith(b"text/html"):
                    extra[b"content-security-policy"] = CSP.encode()
                    extra[b"x-frame-options"] = b"DENY"
                for k, v in extra.items():
                    if k not in have:
                        headers.append((k, v))
                message["headers"] = headers
            await send(message)

        await self.app(scope, receive, wrapped)


async def _reject(
    send: Send, scope: Scope, status: int, code: str, message: str, hint: str
) -> None:
    body = json.dumps(
        {"error": {"code": code, "message": message, "hint": hint, "retryable": False}}
    ).encode()
    if scope["type"] == "websocket":
        await send({"type": "websocket.close", "code": 1008})
        return
    await send(
        {
            "type": "http.response.start",
            "status": status,
            "headers": [
                (b"content-type", b"application/json"),
                (b"content-length", str(len(body)).encode()),
            ],
        }
    )
    await send({"type": "http.response.body", "body": body})


def names_for_display(names: Iterable[str]) -> str:
    return ", ".join(sorted(names))
