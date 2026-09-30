# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Ved Buddaraju

from __future__ import annotations

import json
import os
from collections.abc import AsyncIterator, Iterator
from dataclasses import dataclass
from pathlib import Path

import httpx
import pytest

os.environ.setdefault("GLEANWISE_DATA_DIR", "/tmp/gleanwise-test-unused")
from gleanwise.api.app import create_app
from gleanwise.config import Settings
from gleanwise.testing.fakes import FakeStack


@pytest.fixture(scope="session")
def stack() -> Iterator[FakeStack]:
    s = FakeStack().start()
    yield s
    s.stop()


@pytest.fixture(scope="session")
def pg_uri():
    pgserver = pytest.importorskip("pgserver")
    import tempfile

    srv = pgserver.get_server(tempfile.mkdtemp(), cleanup_mode="delete")
    yield srv.get_uri()
    srv.cleanup()


def make_settings(stack: FakeStack, tmp: Path, **over) -> Settings:
    base = dict(
        data_dir=tmp / "data",
        searxng_url=stack.search_url,
        searxng_managed=False,
        llm_model="openai/fake-model",
        llm_api_base=stack.llm_url,
        llm_api_key="test-key",
        embedder="hash",
        reranker="lexical",
        ssrf_allow_private=True,
        browser_fallback=False,
        log_json=False,
        fetch_timeout_s=5.0,
    )
    base.update(over)
    return Settings(_env_file=None, **base)


@dataclass
class App:
    client: httpx.AsyncClient
    app: object
    stack: FakeStack

    @property
    def svc(self):
        return self.app.state.svc  # type: ignore[attr-defined]

    @property
    def rt(self):
        return self.app.state.rt  # type: ignore[attr-defined]


@pytest.fixture
async def api(stack: FakeStack, tmp_path: Path) -> AsyncIterator[App]:
    stack.reset()
    app = create_app(make_settings(stack, tmp_path))
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://localhost", timeout=60
        ) as c:
            yield App(c, app, stack)


@pytest.fixture
async def make_api(stack: FakeStack, tmp_path: Path) -> AsyncIterator:
    """Factory for tests that need non-default settings."""
    opened: list = []

    async def factory(**over) -> App:
        stack.reset()
        app = create_app(make_settings(stack, tmp_path / f"a{len(opened)}", **over))
        ctx = app.router.lifespan_context(app)
        await ctx.__aenter__()
        c = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://localhost", timeout=60
        )
        opened.append((ctx, c))
        return App(c, app, stack)

    yield factory
    for ctx, c in opened:
        await c.aclose()
        await ctx.__aexit__(None, None, None)


def parse_sse(text: str) -> list[tuple[int, str, dict]]:
    events = []
    for block in text.replace("\r\n", "\n").split("\n\n"):
        eid, name, data = 0, "message", ""
        for line in block.split("\n"):
            if line.startswith("id:"):
                eid = int(line[3:].strip())
            elif line.startswith("event:"):
                name = line[6:].strip()
            elif line.startswith("data:"):
                data += line[5:].strip()
        if data and not block.startswith(":"):
            try:
                events.append((eid, name, json.loads(data)))
            except json.JSONDecodeError:
                continue
    return events


async def run_query(api: App, **body) -> tuple[list[tuple[int, str, dict]], dict]:
    body.setdefault("query", "how do heat pumps work?")
    r = await api.client.post("/query", json=body)
    assert r.status_code == 202, r.text
    acc = r.json()
    s = await api.client.get(acc["stream_url"])
    assert s.status_code == 200
    return parse_sse(s.text), acc
