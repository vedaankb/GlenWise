# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Ved Buddaraju

"""Audit follow-ups: search egress, UI routes vs API routes, cache headers, keychain, link hygiene."""

from __future__ import annotations

import asyncio
import base64
import sys
import types
from pathlib import Path

import pytest

from gleanwise.config import Settings
from gleanwise.egress import EgressGateway
from gleanwise.egress.log import LOG, EgressLog
from gleanwise.privacy import keychain
from gleanwise.search.process import render_settings
from gleanwise.util.text import strip_tracking


# --- SearXNG goes through the gateway ----------------------------------------------------------
def test_searxng_settings_get_gateway_proxy():
    bundled = "use_default_settings: true\nserver:\n  limiter: false\n"
    out = render_settings(bundled, "http://purpose-search:x@127.0.0.1:9999")
    assert "outgoing:" in out and "all://:" in out and "purpose-search" in out
    assert render_settings(bundled, None) == bundled


@pytest.mark.asyncio
async def test_gateway_reads_purpose_from_proxy_user_and_keeps_port(tmp_path: Path):
    async def _echo(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        writer.write(await reader.read(16))
        await writer.drain()
        writer.close()

    echo = await asyncio.start_server(_echo, "127.0.0.1", 0)
    echo_port = echo.sockets[0].getsockname()[1]
    activity = EgressLog()
    settings = Settings(_env_file=None, egress_gateway=True, data_dir=tmp_path)  # type: ignore[call-arg]
    gw = EgressGateway(settings, activity)
    await gw.start()
    first_port = gw.port
    assert gw.proxy_url_for("search") == f"http://purpose-search:x@127.0.0.1:{first_port}"

    cred = base64.b64encode(b"purpose-search:x").decode()
    reader, writer = await asyncio.open_connection("127.0.0.1", gw.port)
    writer.write(
        f"CONNECT 127.0.0.1:{echo_port} HTTP/1.1\r\nProxy-Authorization: Basic {cred}\r\n\r\n".encode()
    )
    await writer.drain()
    assert b"200" in await reader.readline()
    while (await reader.readline()) not in (b"\r\n", b""):
        pass
    writer.write(b"hi")
    await writer.drain()
    assert await reader.read(2) == b"hi"
    writer.close()
    await gw.stop()
    echo.close()
    assert {e["purpose"] for e in activity.recent()} == {"search"}

    # A restart reuses the port, so a long-lived SearXNG child keeps a valid proxy URL.
    gw2 = EgressGateway(settings, EgressLog())
    await gw2.start()
    assert gw2.port == first_port
    await gw2.stop()


@pytest.mark.asyncio
async def test_query_logs_a_search_hop(make_api):
    LOG.clear()
    api = await make_api()
    r = await api.client.post("/search", json={"query": "heat pumps"})
    assert r.status_code == 200
    assert any(e["purpose"] == "search" for e in LOG.recent())


# --- UI pages that share an address with an API route --------------------------------------------
@pytest.fixture
def web_dir(tmp_path: Path) -> Path:
    d = tmp_path / "web"
    (d / "assets").mkdir(parents=True)
    (d / "index.html").write_text("<!doctype html><title>app</title>")
    (d / "assets" / "a-1.js").write_text("1")
    return d


@pytest.mark.asyncio
async def test_browser_navigation_to_shared_routes_gets_the_app(make_api, web_dir: Path):
    api = await make_api(web_dir=str(web_dir))
    for path in ("/settings", "/diagnostics"):
        page = await api.client.get(path, headers={"Accept": "text/html,application/xhtml+xml"})
        assert page.headers["content-type"].startswith("text/html"), path
        assert "<title>app</title>" in page.text
        data = await api.client.get(path, headers={"Accept": "application/json"})
        assert data.headers["content-type"].startswith("application/json"), path
        fetch_default = await api.client.get(path, headers={"Accept": "*/*"})
        assert fetch_default.headers["content-type"].startswith("application/json")


@pytest.mark.asyncio
async def test_app_shell_is_never_cached_but_assets_are_immutable(make_api, web_dir: Path):
    api = await make_api(web_dir=str(web_dir))
    for path in ("/", "/index.html", "/c/some-thread"):
        assert (await api.client.get(path)).headers["cache-control"] == "no-cache", path
    assert "immutable" in (await api.client.get("/assets/a-1.js")).headers["cache-control"]


# --- link hygiene ---------------------------------------------------------------------------------
def test_strip_tracking_keeps_meaningful_params():
    assert (
        strip_tracking("https://a.dev/x?utm_source=n&id=4&fbclid=z#s") == "https://a.dev/x?id=4#s"
    )
    assert strip_tracking("https://github.com/o/r?ref=main") == "https://github.com/o/r?ref=main"
    assert strip_tracking("https://a.dev/x") == "https://a.dev/x"


# --- keychain -------------------------------------------------------------------------------------
def test_keychain_roundtrip_and_fallback(monkeypatch: pytest.MonkeyPatch):
    vault: dict[tuple[str, str], str] = {}
    fake = types.SimpleNamespace(
        set_password=lambda s, n, v: vault.__setitem__((s, n), v),
        get_password=lambda s, n: vault.get((s, n)),
        delete_password=lambda s, n: vault.pop((s, n), None),
    )
    monkeypatch.setitem(sys.modules, "keyring", fake)
    ref = keychain.store_secret("llm_api_key", "sk-secret")
    assert ref == "keychain:llm_api_key" and "sk-secret" not in ref
    assert keychain.load_secret(ref) == "sk-secret"
    assert keychain.load_secret("plain-value") == "plain-value"
    assert keychain.load_secret("") == ""
    keychain.delete_secret("llm_api_key")
    assert keychain.load_secret(ref) == ""

    def boom(*_a: object) -> None:
        raise RuntimeError("no backend")

    monkeypatch.setitem(
        sys.modules, "keyring", types.SimpleNamespace(set_password=boom, get_password=boom)
    )
    assert keychain.store_secret("k", "raw") == "raw"  # falls back to the 0600 settings file
    assert keychain.load_secret("keychain:k") == ""
