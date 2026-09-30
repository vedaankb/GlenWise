# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Ved Buddaraju

from __future__ import annotations

import asyncio
import os
from datetime import UTC, datetime, timedelta

import pytest

from gleanwise.errors import FetchBlocked, FetchFailed
from gleanwise.fetch.http import SafeHTTP
from gleanwise.security import ssrf
from tests.conftest import make_settings, run_query


async def test_robots_txt_is_honoured(api):
    with pytest.raises(FetchBlocked, match="robots"):
        await api.svc.fetcher.fetch(f"{api.stack.web_url}/private/x")


async def test_body_cap_applies_while_streaming(api):
    res = await api.svc.http.get(f"{api.stack.web_url}/big", max_bytes=100_000)
    assert res.truncated and len(res.body) <= 100_000


async def test_unsupported_content_type_is_rejected_cleanly(api):
    with pytest.raises(FetchFailed, match="unsupported"):
        await api.svc.fetcher.fetch(f"{api.stack.web_url}/bin")


async def test_conditional_get_revalidates_with_etag(api):
    url = f"{api.stack.web_url}/p/heat-pumps-explained"
    first = await api.svc.fetcher.fetch(url)
    assert not first.from_cache
    past = datetime.now(UTC) - timedelta(seconds=5)
    await api.svc.store.touch_document(first.doc.id, past, past)  # force expiry
    again = await api.svc.fetcher.fetch(url)
    assert (
        again.from_cache and api.stack.web_state.etag_hits == 1
    )  # 304 → no body re-download/re-parse


async def test_concurrent_identical_fetches_are_deduplicated(api):
    url = f"{api.stack.web_url}/p/sourdough-101"
    await asyncio.gather(*[api.svc.fetcher.fetch(url) for _ in range(6)])
    assert api.stack.web_state.hits.count("sourdough-101") == 1


async def test_every_redirect_hop_is_revalidated(api, monkeypatch):
    """Allow only 127.0.0.1 through the guard, then follow a 302 to the cloud metadata address."""
    real_validate, real_resolve = ssrf.validate_url, ssrf.resolve_public

    def validate(url, *, allow_private=False):
        return url if "127.0.0.1" in url else real_validate(url)

    async def resolve(host, port, *, allow_private=False):
        return ["127.0.0.1"] if host == "127.0.0.1" else await real_resolve(host, port)

    from gleanwise.fetch import http as http_mod

    monkeypatch.setattr(http_mod, "validate_url", validate)
    monkeypatch.setattr(http_mod, "resolve_public", resolve)
    client = SafeHTTP(api.svc.settings.model_copy(update={"ssrf_allow_private": False}))
    try:
        ok = await client.get(f"{api.stack.web_url}/p/sourdough-101")
        assert ok.status == 200
        with pytest.raises(FetchBlocked):
            await client.get(f"{api.stack.web_url}/go-private")
    finally:
        await client.aclose()


async def test_dns_answers_are_pinned_not_rechecked(api, monkeypatch):
    """The connection must go to the address that was validated (no second resolution)."""
    calls: list[str] = []
    real = ssrf.resolve_public

    async def spy(host, port, *, allow_private=False):
        calls.append(host)
        return await real(host, port, allow_private=True)

    from gleanwise.fetch import http as http_mod

    monkeypatch.setattr(http_mod, "resolve_public", spy)
    client = SafeHTTP(api.svc.settings)
    try:
        await client.get(f"{api.stack.web_url}/p/sourdough-101")
    finally:
        await client.aclose()
    assert calls == ["127.0.0.1"]  # resolved once, by the connect step itself


async def test_no_stray_files_outside_data_dir(stack, tmp_path, monkeypatch):
    """Running a query must not litter the working directory (regression: stray ':memory:.ses')."""
    import httpx

    from gleanwise.api.app import create_app

    work = tmp_path / "cwd"
    work.mkdir()
    monkeypatch.chdir(work)
    app = create_app(make_settings(stack, tmp_path / "elsewhere"))
    async with app.router.lifespan_context(app):
        c = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://localhost", timeout=60
        )

        class A:
            client, stack_ = c, stack

        await run_query(A, query="how do heat pumps work?")  # type: ignore[arg-type]
        await c.aclose()
    assert os.listdir(work) == []
