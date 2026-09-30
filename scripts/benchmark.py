# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Ved Buddaraju

"""Optional benchmark runner (FRAMES-style question sets). Not installed by the installer.

Reads JSONL rows with ``question`` (or ``query`` / ``prompt``) and, optionally, ``answer`` (the expected
answer). Runs each question against a running GleanWise, and reports latency, time to first token,
sources used, and, when an expected answer is given, whether it appears in the response.

    uv run --directory services/core python ../../scripts/benchmark.py --dataset frames.jsonl --mode pro
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import statistics
import time
import unicodedata
from pathlib import Path
from typing import Any

import httpx


def normalize(text: str) -> str:
    text = unicodedata.normalize("NFKD", text).lower()
    return re.sub(r"[^a-z0-9]+", " ", text).strip()


async def run_one(client: httpx.AsyncClient, base: str, question: str, mode: str, headers: dict[str, str]) -> dict[str, Any]:
    started = time.perf_counter()
    r = await client.post(f"{base}/query", json={"query": question, "mode": mode, "persist": False}, headers=headers)
    r.raise_for_status()
    qid = r.json()["query_id"]
    first_token: float | None = None
    final = ""
    streamed = ""
    sources = 0
    error: str | None = None
    async with client.stream("GET", f"{base}/stream/{qid}", headers=headers) as stream:
        event = ""
        async for line in stream.aiter_lines():
            if line.startswith("event:"):
                event = line.split(":", 1)[1].strip()
            elif line.startswith("data:"):
                data = json.loads(line.split(":", 1)[1].strip())
                if event == "answer_delta":
                    if first_token is None:
                        first_token = time.perf_counter() - started
                    streamed += data.get("text", "")
                elif event == "answer_upgrade":
                    streamed = ""
                elif event == "done":
                    final = data.get("answer") or streamed
                    sources = len([s for s in data.get("sources", []) if s.get("used_in_answer")])
                    break
                elif event == "error":
                    error = data.get("message", "error")
                    break
    return {
        "question": question,
        "answer": final,
        "sources_used": sources,
        "seconds": round(time.perf_counter() - started, 2),
        "first_token_seconds": round(first_token, 2) if first_token is not None else None,
        "error": error,
    }


async def main_async(args: argparse.Namespace) -> None:
    rows: list[dict[str, Any]] = []
    if args.dataset:
        for line in Path(args.dataset).read_text(encoding="utf-8").splitlines():
            if line.strip():
                obj = json.loads(line)
                rows.append({"question": obj.get("question") or obj.get("query") or obj["prompt"], "expected": obj.get("answer")})
    else:
        rows = [
            {"question": "What is the capital of France?", "expected": "Paris"},
            {"question": "Who wrote Pride and Prejudice?", "expected": "Jane Austen"},
        ]
    headers = {"Authorization": f"Bearer {args.token}"} if args.token else {}
    results: list[dict[str, Any]] = []
    async with httpx.AsyncClient(timeout=args.timeout) as client:
        for row in rows[: args.limit]:
            try:
                res = await run_one(client, args.base, row["question"], args.mode, headers)
            except Exception as exc:  # report the failure and keep going
                res = {"question": row["question"], "error": f"{type(exc).__name__}: {exc}"}
            if row.get("expected") and res.get("answer"):
                res["correct"] = normalize(str(row["expected"])) in normalize(res["answer"])
            results.append(res)

    ok = [r for r in results if not r.get("error")]
    graded = [r for r in ok if "correct" in r]
    summary = {
        "questions": len(results),
        "errors": len(results) - len(ok),
        "median_seconds": statistics.median([r["seconds"] for r in ok]) if ok else None,
        "median_first_token_seconds": statistics.median([r["first_token_seconds"] for r in ok if r.get("first_token_seconds") is not None])
        if any(r.get("first_token_seconds") is not None for r in ok)
        else None,
        "accuracy": round(sum(r["correct"] for r in graded) / len(graded), 3) if graded else None,
        "graded": len(graded),
    }
    Path(args.out).write_text(json.dumps({"summary": summary, "results": results}, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(summary, indent=2))
    print(f"Wrote {args.out}")


def main() -> None:
    p = argparse.ArgumentParser(description="Optional benchmark against a running GleanWise")
    p.add_argument("--base", default="http://127.0.0.1:8787")
    p.add_argument("--token", default="", help="API token, if the server requires one")
    p.add_argument("--dataset", help="JSONL with question (and optional answer) fields")
    p.add_argument("--mode", default="quick", choices=["quick", "pro", "deep"])
    p.add_argument("--limit", type=int, default=20)
    p.add_argument("--timeout", type=float, default=300.0)
    p.add_argument("--out", default="benchmark-report.json")
    asyncio.run(main_async(p.parse_args()))


if __name__ == "__main__":
    main()
