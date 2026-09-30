# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Ved Buddaraju

"""Command line: serve, doctor, prefetch, token, openapi."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path


def serve(argv: list[str] | None = None) -> None:
    import uvicorn

    from gleanwise.config import Settings

    p = argparse.ArgumentParser(prog="gw-core serve")
    p.add_argument("--host")
    p.add_argument("--port", type=int)
    p.add_argument("--reload", action="store_true")
    a = p.parse_args(argv)
    s = Settings()
    uvicorn.run(
        "gleanwise.api.app:create_app",
        factory=True,
        host=a.host or s.host,
        port=a.port or s.port,
        reload=a.reload,
        log_level="info",
        proxy_headers=s.profile == "server",
        forwarded_allow_ips="*" if s.profile == "server" else "127.0.0.1",
        timeout_graceful_shutdown=10,
    )


def _print(ok: bool, name: str, detail: str, hint: str | None = None) -> None:
    mark = "✓" if ok else "✗"
    print(f"  {mark} {name:<11} {detail}")
    if not ok and hint:
        print(f"      → {hint}")


async def _doctor() -> int:
    from gleanwise.config import Settings
    from gleanwise.services import Services

    s = Settings().overlay_ui_settings()
    print(f"GleanWise doctor — data dir {s.resolved_data_dir()}\n")
    svc = Services(s)
    bad = 0
    try:
        await svc.store.init()
        info = await svc.store.ping()
        _print(
            True,
            "storage",
            f"{info['backend']} schema v{info.get('schema')} · vectors: {info.get('vector_index')}",
        )
        ok, detail = await svc.search.ping()
        bad += not ok
        _print(
            ok,
            "search",
            f"{s.searxng_url} · {detail}",
            "Start SearXNG, or run the installer again (it can set one up without Docker).",
        )
        _print(
            bool(s.llm_model),
            "model",
            s.llm_model or "not configured",
            "Open the app → Settings, or set GLEANWISE_LLM_MODEL.",
        )
        bad += not s.llm_model
        try:
            await svc.embedder.warm()
            _print(True, "embeddings", svc.embedder.name)
        except Exception as exc:
            bad += 1
            _print(
                False,
                "embeddings",
                str(exc)[:100],
                "Needs a one-time model download: run `gleanwise-core prefetch` while online.",
            )
        await svc.reranker.warm()
        rr = svc.reranker
        _print(
            rr.degraded_reason is None,
            "reranker",
            rr.name if not rr.degraded_reason else rr.degraded_reason,
            "Run `gleanwise-core prefetch` while online.",
        )
        from gleanwise.api.static import find_web_dir

        web = find_web_dir(s)
        _print(
            web is not None,
            "web ui",
            str(web) if web else "not built",
            "Run `pnpm --filter @gleanwise/web build`.",
        )
    finally:
        await svc.close()
    print("\nAll good." if not bad else f"\n{bad} thing(s) need attention.")
    return 1 if bad else 0


async def _prefetch() -> int:
    from gleanwise.config import Settings
    from gleanwise.embed.embedder import build_embedder
    from gleanwise.rank.reranker import build_reranker

    s = Settings().overlay_ui_settings()
    print(f"Downloading models into {s.resolved_data_dir() / 'models'} …")
    emb, rr = build_embedder(s), build_reranker(s)
    await emb.warm()
    print(f"  ✓ embeddings  {emb.name}")
    await rr.warm()
    print(
        f"  {'✓' if not rr.degraded_reason else '✗'} reranker    {rr.name} {rr.degraded_reason or ''}"
    )
    return 0


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="gleanwise")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("serve", help="run the server")
    sub.add_parser("doctor", help="check the installation and explain how to fix problems")
    sub.add_parser("prefetch", help="download local models now (for offline use)")
    sub.add_parser("token", help="print a new random API token")
    o = sub.add_parser("openapi", help="write the OpenAPI schema")
    o.add_argument("out", nargs="?", default="-")
    args, rest = parser.parse_known_args(argv)

    if args.cmd == "serve":
        serve(rest)
    elif args.cmd == "doctor":
        sys.exit(asyncio.run(_doctor()))
    elif args.cmd == "prefetch":
        sys.exit(asyncio.run(_prefetch()))
    elif args.cmd == "token":
        from gleanwise.config import generate_token

        print(generate_token())
    elif args.cmd == "openapi":
        from gleanwise.api.app import create_app
        from gleanwise.config import Settings

        schema = create_app(Settings(data_dir=Path("/tmp/gleanwise-openapi"))).openapi()  # noqa: S108
        text = json.dumps(schema, indent=2, ensure_ascii=False) + "\n"
        if args.out == "-":
            sys.stdout.write(text)
        else:
            Path(args.out).write_text(text, encoding="utf-8")


if __name__ == "__main__":
    main()
