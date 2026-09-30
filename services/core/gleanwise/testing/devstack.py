# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Ved Buddaraju

"""Run a complete, offline GleanWise for UI development and browser tests.

    python -m gleanwise.testing.devstack [--port 8787] [--unconfigured] [--token TOKEN]

Starts the fake web, fake SearXNG and fake OpenAI-compatible LLM on fixed local ports, then serves the
real core (and the built web UI, when present) wired to them. Nothing touches the internet.
`--unconfigured` starts the core with no LLM so the first-run wizard can be exercised; the wizard can
then be pointed at the printed fake LLM URL.
"""

from __future__ import annotations

import argparse
import tempfile
from pathlib import Path

import uvicorn

from gleanwise.api.app import create_app
from gleanwise.config import Settings
from gleanwise.testing.fakes import FakeStack


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(prog="devstack")
    p.add_argument("--port", type=int, default=8787)
    p.add_argument("--data-dir", type=Path)
    p.add_argument("--unconfigured", action="store_true", help="start with no LLM configured")
    p.add_argument("--token", help="require this bearer token")
    p.add_argument("--fake-ports", default="18081,18082,18083", help="web,search,llm")
    a = p.parse_args(argv)

    ports = tuple(int(x) for x in a.fake_ports.split(","))
    stack = FakeStack(ports=ports).start()  # type: ignore[arg-type]
    data_dir = a.data_dir or Path(tempfile.mkdtemp(prefix="gleanwise-dev-"))
    over: dict[str, object] = {}
    if not a.unconfigured:
        over |= {
            "llm_model": "openai/fake-model",
            "llm_api_base": stack.llm_url,
            "llm_api_key": "test-key",
        }
    if a.token:
        over["api_token"] = a.token
    settings = Settings(  # type: ignore[call-arg]
        _env_file=None,
        data_dir=data_dir,
        port=a.port,
        searxng_url=stack.search_url,
        searxng_managed=False,
        embedder="hash",
        reranker="lexical",
        ssrf_allow_private=True,
        browser_fallback=False,
        log_json=False,
        **over,  # type: ignore[arg-type]
    )
    print(f"fake web    {stack.web_url}")  # noqa: T201
    print(f"fake search {stack.search_url}")  # noqa: T201
    print(f"fake llm    {stack.llm_url}")  # noqa: T201
    print(f"data dir    {data_dir}")  # noqa: T201
    try:
        uvicorn.run(create_app(settings), host="127.0.0.1", port=a.port, log_level="warning")
    finally:
        stack.stop()


if __name__ == "__main__":
    main()
