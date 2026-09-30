# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Ved Buddaraju

from __future__ import annotations

from tests.conftest import run_query


async def test_quick_flow_streams_and_persists(api):
    events, acc = await run_query(api, mode="quick")
    names = [n for _, n, _ in events]
    ids = [i for i, _, _ in events]
    assert ids == list(range(1, len(ids) + 1)), "event ids are dense and ordered"
    assert names[0] == "plan" and names[-1] == "done"
    for expected in (
        "sources",
        "answer_delta",
        "answer_upgrade",
        "answer_complete",
        "source_update",
    ):
        assert expected in names, f"missing {expected}: {names}"
    done = events[-1][2]
    assert done["status"] == "complete" and done["answer"]
    assert done["citations"] and all(c["url"].startswith("http") for c in done["citations"])
    # citation numbers refer to real, registered sources
    src_ids = {s["id"] for s in done["sources"]}
    assert {c["number"] for c in done["citations"]} <= src_ids
    assert done["usage"]["prompt_tokens"] > 0

    thread = (await api.client.get(f"/threads/{acc['thread_id']}")).json()
    assert [m["role"] for m in thread["messages"]] == ["user", "assistant"]
    assert thread["messages"][1]["content"] == done["answer"]
    listed = (await api.client.get("/threads")).json()
    assert [t["id"] for t in listed] == [acc["thread_id"]]


async def test_replay_with_last_event_id(api):
    events, acc = await run_query(api)
    total = len(events)
    r = await api.client.get(acc["stream_url"], headers={"Last-Event-ID": str(total - 2)})
    from tests.conftest import parse_sse

    replay = parse_sse(r.text)
    assert [i for i, _, _ in replay] == [total - 1, total]
    assert replay[-1][1] == "done"


async def test_unknown_query_is_404_envelope(api):
    r = await api.client.get("/stream/deadbeef")
    assert r.status_code == 404 and r.json()["error"]["code"] == "not_found"


async def test_full_pipeline_on_postgres(make_api, pg_uri):
    import asyncpg

    c = await asyncpg.connect(pg_uri)
    await c.execute("DROP SCHEMA public CASCADE; CREATE SCHEMA public;")
    await c.close()
    api = await make_api(database_url=pg_uri)
    assert api.svc.store.backend == "postgres"
    events, acc = await run_query(api, mode="pro")
    assert events[-1][1] == "done" and events[-1][2]["citations"]
    thread = (await api.client.get(f"/threads/{acc['thread_id']}")).json()
    assert [m["role"] for m in thread["messages"]] == ["user", "assistant"]
