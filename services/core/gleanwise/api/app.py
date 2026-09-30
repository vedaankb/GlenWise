# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Ved Buddaraju

"""FastAPI application factory."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from gleanwise import __version__
from gleanwise.api.routes import health, openai, operator, privacy, query, threads, tools
from gleanwise.api.routes import settings as settings_routes
from gleanwise.api.static import UIFiles, UiNavigation, find_web_dir
from gleanwise.config import Settings, set_settings
from gleanwise.errors import GleanWiseError
from gleanwise.index.base import Store
from gleanwise.pipeline.runtime import QueryRuntime
from gleanwise.security.guards import SecurityGuard, SecurityHeaders, effective_cors_origins
from gleanwise.services import Services
from gleanwise.telemetry.logging import configure_logging

log = logging.getLogger(__name__)

DESCRIPTION = """Local-first answer engine. `POST /query` then stream `GET /stream/{id}` (SSE).
OpenAI-compatible endpoint: `POST /v1/chat/completions`."""


def _error(
    status: int, code: str, message: str, hint: str | None = None, **extra: Any
) -> JSONResponse:
    body = {
        "code": code,
        "message": message,
        "hint": hint,
        "action": None,
        "retryable": False,
        **extra,
    }
    return JSONResponse({"error": body}, status_code=status)


def create_app(settings: Settings | None = None, *, store: Store | None = None) -> FastAPI:
    base = settings or Settings()
    env_locked = set(base.model_fields_set)  # fields the operator fixed via environment
    effective = base.overlay_ui_settings()
    set_settings(effective)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        configure_logging(json_logs=effective.log_json)
        svc = Services(effective, store=store)
        await svc.start()
        app.state.svc = svc
        app.state.rt = QueryRuntime(svc)
        if effective.host in {"0.0.0.0", "::"} and not effective.api_token:  # noqa: S104
            log.warning(
                "Listening on all interfaces without GLEANWISE_API_TOKEN: anyone on your network can use this instance."
            )
        try:
            yield
        finally:
            rt: QueryRuntime = app.state.rt
            for job in list(rt.jobs.values()):
                if not job.finished:
                    rt.cancel(job.query_id)
            await asyncio.sleep(0)  # let cancelled jobs emit their terminal events
            await svc.close()

    app = FastAPI(
        title="GleanWise",
        version=__version__,
        description=DESCRIPTION,
        lifespan=lifespan,
        docs_url="/docs",
        redoc_url=None,
    )
    app.state.settings = effective
    app.state.env_locked = env_locked

    # Outermost first: guard → CORS → headers.
    app.add_middleware(SecurityHeaders)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=effective_cors_origins(effective),
        allow_credentials=False,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "Last-Event-ID", "Accept"],
        expose_headers=["Content-Disposition"],
        max_age=600,
    )
    app.add_middleware(SecurityGuard, settings=effective)

    # --- errors: one envelope everywhere ---------------------------------------------------------
    @app.exception_handler(GleanWiseError)
    async def _gleanwise(request: Request, exc: GleanWiseError) -> JSONResponse:
        if request.url.path.startswith("/v1/"):
            return JSONResponse(openai._oa_error(exc), status_code=exc.status)
        return JSONResponse({"error": exc.to_payload()}, status_code=exc.status)

    @app.exception_handler(RequestValidationError)
    async def _validation(request: Request, exc: RequestValidationError) -> JSONResponse:
        first = exc.errors()[0] if exc.errors() else {}
        where = ".".join(str(p) for p in first.get("loc", []) if p != "body")
        msg = f"Invalid request{': ' + where if where else ''} — {first.get('msg', 'bad value')}"
        if request.url.path.startswith("/v1/"):
            return JSONResponse(
                {
                    "error": {
                        "message": msg,
                        "type": "invalid_request_error",
                        "code": "bad_request",
                        "param": where or None,
                    }
                },
                status_code=422,
            )
        return _error(422, "bad_request", msg)

    @app.exception_handler(StarletteHTTPException)
    async def _http(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        code = {
            404: "not_found",
            405: "method_not_allowed",
            401: "unauthorized",
            403: "forbidden",
        }.get(exc.status_code, "http_error")
        return _error(exc.status_code, code, str(exc.detail))

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception) -> JSONResponse:
        log.exception("unhandled error on %s", request.url.path)
        return _error(
            500, "internal", "Something went wrong on our side.", "Check the server logs."
        )

    for r in (
        health.router,
        query.router,
        threads.router,
        tools.router,
        settings_routes.router,
        operator.router,
        privacy.router,
        openai.router,
    ):
        app.include_router(r)

    web = find_web_dir(effective)
    if web is not None:
        app.add_middleware(UiNavigation)
        app.mount("/", UIFiles(directory=web, html=True), name="ui")
    else:

        @app.get("/", include_in_schema=False)
        async def root() -> dict[str, str]:
            return {
                "name": "GleanWise",
                "version": __version__,
                "docs": "/docs",
                "ui": "not built — run `pnpm --filter @gleanwise/web build`",
            }

    return app
