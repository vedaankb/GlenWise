# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Ved Buddaraju

"""Privacy suite: Strict Local, redaction, egress gateway, private threads, tracker blocklist."""

from __future__ import annotations

import asyncio

import pytest

from gleanwise.egress import (
    EgressGateway,
    is_local_host,
    is_local_llm_endpoint,
    redact_pii,
    restore_pii,
)
from gleanwise.egress.policy import assert_strict_local_llm
from gleanwise.errors import BadRequest
from gleanwise.fetch.trackers import is_tracker_url


def test_is_local_host_and_llm():
    assert is_local_host("127.0.0.1")
    assert is_local_host("localhost")
    assert is_local_host("ollama.lan", ["ollama.lan"])
    assert not is_local_host("api.openai.com")
    assert is_local_llm_endpoint("ollama_chat/llama3", "", [])
    assert is_local_llm_endpoint("openai/gpt", "http://127.0.0.1:1234/v1", [])
    assert not is_local_llm_endpoint("openai/gpt-4o", "https://api.openai.com/v1", [])


def test_strict_local_blocks_cloud():
    with pytest.raises(BadRequest):
        assert_strict_local_llm("openai/gpt-4o", "https://api.openai.com/v1", [])


def test_pii_roundtrip():
    text = "Write to ada@example.com or call +1 (415) 555-0100. SSN 123-45-6789."
    red, mapping = redact_pii(text)
    assert "ada@example.com" not in red
    assert "123-45-6789" not in red
    assert "[EMAIL_" in red
    assert restore_pii(red, mapping) == text


def test_tracker_blocklist():
    assert is_tracker_url("https://www.google-analytics.com/g/collect")
    assert is_tracker_url("https://connect.facebook.net/en_US/fbevents.js")
    assert not is_tracker_url("https://en.wikipedia.org/wiki/Privacy")


@pytest.mark.asyncio
async def test_egress_gateway_connect_and_log():
    from gleanwise.config import Settings
    from gleanwise.egress.log import EgressLog

    # Tiny echo TLS-less TCP server to CONNECT to.
    async def _echo(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        data = await reader.read(64)
        writer.write(data)
        await writer.drain()
        writer.close()

    echo = await asyncio.start_server(_echo, "127.0.0.1", 0)
    echo_port = echo.sockets[0].getsockname()[1]

    activity = EgressLog()
    settings = Settings(
        _env_file=None,  # type: ignore[call-arg]
        egress_gateway=True,
        strict_local=False,
        data_dir="/tmp/gleanwise-egress-test",
    )
    gw = EgressGateway(settings, activity)
    await gw.start()
    assert gw.proxy_url

    # Manual CONNECT through the gateway.
    reader, writer = await asyncio.open_connection("127.0.0.1", gw.port)
    writer.write(f"CONNECT 127.0.0.1:{echo_port} HTTP/1.1\r\nProxy-Purpose: fetch\r\n\r\n".encode())
    await writer.drain()
    status = await reader.readline()
    assert b"200" in status
    while True:
        line = await reader.readline()
        if line in (b"\r\n", b"\n", b""):
            break
    writer.write(b"ping")
    await writer.drain()
    assert await reader.read(4) == b"ping"
    writer.close()
    await writer.wait_closed()
    await gw.stop()
    echo.close()
    await echo.wait_closed()

    entries = activity.recent()
    assert entries, "gateway should have logged the CONNECT"
    assert any(e["host"] == "127.0.0.1" for e in entries)


@pytest.mark.asyncio
async def test_private_query_skips_persistence(make_api):
    api = await make_api()
    r = await api.client.post(
        "/query",
        json={
            "query": "how does a heat pump work",
            "mode": "quick",
            "private": True,
            "persist": True,
        },
    )
    assert r.status_code in {200, 202}, r.text
    body = r.json()
    qid, tid = body["query_id"], body["thread_id"]
    # Drain the stream
    async with api.client.stream("GET", f"/stream/{qid}") as stream:
        async for _ in stream.aiter_lines():
            pass
    # Thread should have no messages (private → persist forced off).
    t = await api.client.get(f"/threads/{tid}")
    # Thread may 404 if never persisted, or exist empty — either is fine.
    if t.status_code == 200:
        msgs = t.json().get("messages") or t.json().get("turns") or []
        assert msgs == [] or all(m.get("role") != "assistant" for m in msgs)


@pytest.mark.asyncio
async def test_strict_local_rejects_cloud_query(make_api):
    api = await make_api(
        strict_local=True,
        llm_model="openai/gpt-4o",
        llm_api_base="https://api.openai.com/v1",
        llm_api_key="sk-test",
    )
    r = await api.client.post("/query", json={"query": "hi", "mode": "quick"})
    if r.status_code >= 400:
        assert r.status_code in {400, 422, 424}
        return
    assert r.status_code in {200, 202}
    qid = r.json()["query_id"]
    saw_error = False
    async with api.client.stream("GET", f"/stream/{qid}") as stream:
        event = ""
        async for line in stream.aiter_lines():
            if line.startswith("event:"):
                event = line.split(":", 1)[1].strip()
            elif line.startswith("data:") and event == "error":
                saw_error = True
                break
    assert saw_error


@pytest.mark.asyncio
async def test_operator_metrics_require_consent(make_api):
    api = await make_api(operator_metrics=False)
    r = await api.client.get("/metrics")
    assert r.status_code == 403
    api2 = await make_api(operator_metrics=True)
    r2 = await api2.client.get("/metrics")
    assert r2.status_code == 200


@pytest.mark.asyncio
async def test_egress_activity_endpoint(make_api):
    api = await make_api()
    r = await api.client.get("/privacy/egress")
    assert r.status_code == 200
    body = r.json()
    assert "entries" in body
    assert "gateway" in body
