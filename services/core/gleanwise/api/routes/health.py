# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Ved Buddaraju

from __future__ import annotations

import time
from xml.sax.saxutils import escape

from fastapi import APIRouter, Request, Response

from gleanwise import __version__
from gleanwise.api.deps import Auth, SvcDep
from gleanwise.errors import GleanWiseError
from gleanwise.models import (
    HealthComponent,
    HealthResponse,
    LiveResponse,
    SetupTestRequest,
    SetupTestResult,
)

router = APIRouter(tags=["health"])


@router.get("/livez", response_model=LiveResponse, summary="Process is up")
async def livez() -> LiveResponse:
    return LiveResponse(version=__version__)


@router.get("/opensearch.xml", include_in_schema=False)
async def opensearch(request: Request) -> Response:
    """Lets browsers register the app as a search engine (`/?q=` searches immediately)."""
    base = escape(str(request.base_url).rstrip("/"))
    xml = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<OpenSearchDescription xmlns="http://a9.com/-/spec/opensearch/1.1/">'
        "<ShortName>GleanWise</ShortName>"
        "<Description>Search with cited answers</Description>"
        "<InputEncoding>UTF-8</InputEncoding>"
        f'<Image width="192" height="192" type="image/png">{base}/icons/icon-192.png</Image>'
        f'<Url type="text/html" template="{base}/?q={{searchTerms}}"/>'
        "</OpenSearchDescription>"
    )
    return Response(xml, media_type="application/opensearchdescription+xml")


async def _components(svc: SvcDep, *, deep: bool) -> list[HealthComponent]:
    s = svc.settings
    out: list[HealthComponent] = []
    try:
        info = await svc.store.ping()
        out.append(
            HealthComponent(
                name="storage",
                ok=True,
                detail=f"{info['backend']} · {info.get('vector_index', '')}".strip(" ·"),
            )
        )
    except Exception as exc:
        out.append(
            HealthComponent(
                name="storage",
                ok=False,
                detail=type(exc).__name__,
                hint="Check the data directory permissions and free disk space.",
            )
        )

    ok, detail = await svc.search.ping()
    out.append(
        HealthComponent(
            name="search",
            ok=ok,
            detail=f"{s.searxng_url} · {detail}",
            hint=None
            if ok
            else "Start SearXNG (`gleanwise doctor` explains how) or fix its URL in Settings.",
            action=None if ok else "open_settings",
        )
    )
    configured = bool(s.llm_model)
    out.append(
        HealthComponent(
            name="llm",
            ok=configured,
            detail=s.llm_model or "not configured",
            hint=None if configured else "Choose a model in Settings.",
            action=None if configured else "open_settings",
        )
    )
    warm = svc.warm.get("embedder", "idle")
    out.append(
        HealthComponent(
            name="embeddings",
            ok=warm in {"ready", "idle", "loading"},
            detail=f"{svc.embedder.name} · {warm}",
            hint="First run downloads a small model; this can take a minute."
            if warm == "loading"
            else (
                "Switch the embedder in Settings or check your connection."
                if warm.startswith("error")
                else None
            ),
        )
    )
    rr = svc.reranker
    out.append(
        HealthComponent(
            name="reranker",
            ok=True,
            detail=f"{rr.name} · {'degraded: ' + rr.degraded_reason if rr.degraded_reason else svc.warm.get('reranker', 'idle')}",
        )
    )
    return out


@router.get("/readyz", response_model=HealthResponse, summary="Can this instance serve traffic?")
async def readyz(svc: SvcDep, response: Response) -> HealthResponse:
    comps = await _components(svc, deep=False)
    storage_ok = next(c.ok for c in comps if c.name == "storage")
    if not storage_ok:
        response.status_code = 503
    return HealthResponse(
        ok=all(c.ok for c in comps if c.name in {"storage", "search"}),
        version=__version__,
        components=comps,
    )


@router.get("/health", response_model=HealthResponse, include_in_schema=False)
async def health(svc: SvcDep, response: Response) -> HealthResponse:
    return await readyz(svc, response)


@router.get(
    "/diagnostics",
    response_model=HealthResponse,
    dependencies=[Auth],
    summary="Full diagnostics with fixes",
)
async def diagnostics(svc: SvcDep) -> HealthResponse:
    comps = await _components(svc, deep=True)
    stats = await svc.store.stats()
    comps.append(
        HealthComponent(
            name="cache",
            ok=True,
            detail=f"{stats['documents']} pages · {stats['chunks']} passages · {stats['threads']} conversations",
        )
    )
    comps.append(
        HealthComponent(
            name="uptime",
            ok=True,
            detail=f"{int(time.time() - svc.started_at)}s · profile {svc.settings.profile}",
        )
    )
    return HealthResponse(ok=all(c.ok for c in comps), version=__version__, components=comps)


@router.post(
    "/setup/test",
    response_model=SetupTestResult,
    dependencies=[Auth],
    summary="Test settings before saving",
)
async def setup_test(body: SetupTestRequest, svc: SvcDep) -> SetupTestResult:
    """Used by the first-run wizard: proves the model, key and search backend actually work."""
    from gleanwise.llm.client import LLM
    from gleanwise.search.client import SearchClient

    trial = svc.settings.model_copy(
        update={k: v for k, v in body.model_dump().items() if v not in (None, "")}
    )
    llm_c: HealthComponent
    try:
        reply = await LLM(trial).complete(
            [{"role": "user", "content": "Reply with the single word: OK"}],
            max_tokens=8,
            timeout=25,
        )
        llm_c = HealthComponent(
            name="llm", ok=True, detail=f"{trial.llm_model} replied “{reply[:20]}”"
        )
    except GleanWiseError as exc:
        llm_c = HealthComponent(
            name="llm", ok=False, detail=exc.message, hint=exc.hint, action=exc.action
        )
    sc = SearchClient(trial)
    try:
        ok, detail = await sc.ping()
    finally:
        await sc.aclose()
    search_c = HealthComponent(
        name="search",
        ok=ok,
        detail=detail,
        hint=None if ok else "Start SearXNG or correct its URL.",
        action=None if ok else "open_settings",
    )
    warm = svc.warm.get("embedder", "idle")
    emb_c = HealthComponent(
        name="embeddings",
        ok=not warm.startswith("error"),
        detail=f"{svc.embedder.name} · {warm}",
        hint="The first run downloads a small model." if warm in {"idle", "loading"} else None,
    )
    return SetupTestResult(llm=llm_c, search=search_c, embeddings=emb_c)
