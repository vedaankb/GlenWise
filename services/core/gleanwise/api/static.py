# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Ved Buddaraju

"""Serve the exported web UI from the same origin as the API (no CORS, no second server)."""

from __future__ import annotations

from pathlib import Path

from starlette.exceptions import HTTPException
from starlette.responses import Response
from starlette.staticfiles import StaticFiles
from starlette.types import ASGIApp, Receive, Scope, Send

from gleanwise.config import Settings


def find_web_dir(settings: Settings) -> Path | None:
    candidates: list[Path] = []
    if settings.web_dir:
        candidates.append(Path(settings.web_dir).expanduser())
    here = Path(__file__).resolve()
    candidates.append(here.parents[1] / "web")  # wheel layout: gleanwise/web
    for parent in here.parents:
        candidates.append(parent / "apps" / "web" / "dist")  # monorepo checkout
    for c in candidates:
        if (c / "index.html").is_file():
            return c
    return None


class UIFiles(StaticFiles):
    """StaticFiles + SPA fallback (client-side routes) + sane cache headers."""

    async def get_response(self, path: str, scope: Scope) -> Response:
        try:
            resp = await super().get_response(path, scope)
        except HTTPException as exc:
            last = path.rsplit("/", 1)[-1]
            if exc.status_code == 404 and "." not in last and not path.startswith("assets/"):
                resp = await super().get_response("index.html", scope)
            else:
                raise
        if resp.status_code == 200:
            last = path.rsplit("/", 1)[-1]
            if path.startswith("assets/"):  # content-hashed by the bundler
                resp.headers["Cache-Control"] = "public, max-age=31536000, immutable"
            elif (
                path in {"", ".", "/"}  # the app shell served for "/"
                or path.endswith(
                    (".html", "sw.js", "manifest.webmanifest", "manifest.json", "theme-init.js")
                )
                or "." not in last
            ):
                resp.headers["Cache-Control"] = "no-cache"
            else:
                resp.headers["Cache-Control"] = "public, max-age=86400"
        return resp


# UI pages whose address is also an API endpoint: a browser navigation must get the app, not JSON.
UI_PAGES_SHARED_WITH_API = {"/settings", "/diagnostics"}


class UiNavigation:
    """Serve the SPA for browser navigations to UI routes that share a path with the API."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if (
            scope["type"] == "http"
            and scope["method"] == "GET"
            and scope["path"].rstrip("/") in UI_PAGES_SHARED_WITH_API
        ):
            h = {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope["headers"]}
            navigating = h.get("sec-fetch-dest") == "document" or (
                "text/html" in h.get("accept", "") and "application/json" not in h.get("accept", "")
            )
            if navigating:
                scope = {**scope, "path": "/index.html", "raw_path": b"/index.html"}
        await self.app(scope, receive, send)
