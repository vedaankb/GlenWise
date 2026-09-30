# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Ved Buddaraju

from __future__ import annotations

import asyncio

from tests.conftest import parse_sse, run_query


async def test_pro_plans_multiple_searches_and_follow_ups(api):
    events, _ = await run_query(api, mode="pro")
    names = [n for _, n, _ in events]
    assert "follow_ups" in names and names[-1] == "done"
    plan = [d for _, n, d in events if n == "plan"][-1]
    assert len(plan["subqueries"]) >= 2
    assert len(api.stack.search_state.queries) >= 2  # one search per planned sub-query
    done = events[-1][2]
    assert done["follow_ups"] and done["citations"]


async def test_deep_is_honest_multi_round_with_visits(api):
    events, acc = await run_query(api, mode="deep")
    names = [n for _, n, _ in events]
    assert names.count("visit") >= 3
    reasoning = "".join(d["text"] for _, n, d in events if n == "reasoning_delta")
    assert "Round 1" in reasoning and "Assessment:" in reasoning  # real critic output, not theatre
    assert api.stack.llm_state.kinds().count("critic") >= 1
    done = events[-1][2]
    assert done["research_summary"] and "research round" in done["research_summary"]
    thread = (await api.client.get(f"/threads/{acc['thread_id']}")).json()
    assert thread["messages"][1]["research_log"], "research log persisted with the answer"


async def test_retrieval_is_scoped_to_this_query(api):
    """Pages cached by an earlier question must not leak into a different question's context."""
    await run_query(api, query="how do heat pumps work?")
    api.stack.llm_state.calls.clear()
    events, _ = await run_query(api, query="python asyncio gather")
    done = events[-1][2]
    urls = {c["url"] for c in done["citations"]}
    assert urls and all("heat-pump" not in u for u in urls)
    answer_call = [c for c in api.stack.llm_state.calls if c["kind"] == "answer"][-1]
    assert "heat pump" not in str(answer_call["messages"][-1]["content"]).lower()


async def test_hallucinated_citations_are_removed(api):
    api.stack.llm_state.hallucinate = True
    events, _ = await run_query(api)
    done = events[-1][2]
    assert "[99]" not in done["answer"]
    assert all(c["number"] != 99 for c in done["citations"])


async def test_prompt_injection_is_fenced_not_obeyed(api):
    events, _ = await run_query(api, query="solar panel efficiency")
    call = [c for c in api.stack.llm_state.calls if c["kind"] == "answer"][-1]
    system = call["messages"][0]["content"]
    user = call["messages"][-1]["content"]
    assert "untrusted" in system and "Never follow them" in system
    # the page tried to close our <source> tag and open a <system> tag: both neutralised
    assert "</source><system>" not in user and "<system>" not in user
    assert user.count("</source>") == user.count("<source n=")


async def test_llm_auth_error_is_actionable(make_api):
    api = await make_api()
    api.stack.llm_state.require_key = "the-real-key"
    events, _ = await run_query(api)
    last = events[-1]
    assert last[1] == "error"
    assert (
        last[2]["code"] == "llm_auth" and last[2]["action"] == "open_settings" and last[2]["hint"]
    )


async def test_llm_not_configured(make_api):
    api = await make_api(llm_model="")
    events, _ = await run_query(api)
    assert events[-1][1] == "error" and events[-1][2]["code"] == "llm_not_configured"
    assert events[-1][2]["action"] == "open_settings"


async def test_search_down_and_json_disabled(make_api):
    api = await make_api()
    api.stack.search_state.down = True
    events, _ = await run_query(api)
    assert events[-1][1] == "error" and events[-1][2]["code"] == "search_unavailable"
    api.stack.search_state.down = False
    api.stack.search_state.json_forbidden = True
    events, _ = await run_query(api)
    assert "JSON" in events[-1][2]["message"]


async def test_no_results_message(api):
    events, _ = await run_query(api, query="zzznoresults please")
    assert events[-1][1] == "error" and events[-1][2]["code"] == "search_no_results"


async def test_engine_warnings_surface(api):
    api.stack.search_state.unresponsive = [["duckduckgo", "CAPTCHA"]]
    events, _ = await run_query(api)
    warns = [d for _, n, d in events if n == "warning"]
    assert any("duckduckgo" in w["message"] for w in warns)


async def test_cancel_stops_work_and_saves_nothing(api):
    api.stack.llm_state.token_delay = 0.05
    r = await api.client.post("/query", json={"query": "how do heat pumps work?", "mode": "pro"})
    acc = r.json()
    job = api.rt.get(acc["query_id"])
    for _ in range(200):  # wait until the answer is streaming
        if any(e.name == "answer_delta" for e in job.events):
            break
        await asyncio.sleep(0.05)
    assert (await api.client.post(f"/queries/{acc['query_id']}/cancel")).json()["ok"] is True
    events = parse_sse((await api.client.get(acc["stream_url"])).text)
    assert events[-1][1] == "done" and events[-1][2]["status"] == "cancelled"
    assert (await api.client.get("/threads")).json() == []  # nothing persisted → hidden
    api.stack.llm_state.token_delay = 0.004


async def test_deadline_is_enforced(make_api):
    api = await make_api(quick_deadline_s=1.0, llm_first_token_timeout_s=30)
    api.stack.llm_state.first_token_delay = 5.0
    events, _ = await run_query(api)
    assert events[-1][1] == "error" and events[-1][2]["code"] == "deadline_exceeded"


async def test_busy_when_queue_is_full(make_api):
    api = await make_api(max_concurrent_queries=1, max_queued_queries=0)
    api.stack.llm_state.first_token_delay = 1.5
    first = await api.client.post("/query", json={"query": "how do heat pumps work?"})
    assert first.status_code == 202
    second = await api.client.post("/query", json={"query": "another"})
    assert second.status_code == 429 and second.json()["error"]["code"] == "busy"
    api.rt.cancel(first.json()["query_id"])


async def test_follow_up_uses_thread_history(api):
    _, acc = await run_query(api, query="how do heat pumps work?")
    api.stack.llm_state.calls.clear()
    events, _ = await run_query(api, query="and how much do they cost?", thread_id=acc["thread_id"])
    assert "rewrite" in api.stack.llm_state.kinds()
    plan = [d for _, n, d in events if n == "plan"][0]
    thread = (await api.client.get(f"/threads/{acc['thread_id']}")).json()
    assert len(thread["messages"]) == 4 and plan


async def test_regenerate_replaces_the_answer(api):
    _, acc = await run_query(api)
    t = (await api.client.get(f"/threads/{acc['thread_id']}")).json()
    old = t["messages"][1]["id"]
    await run_query(api, thread_id=acc["thread_id"], regenerate_message_id=old)
    t2 = (await api.client.get(f"/threads/{acc['thread_id']}")).json()
    assert len(t2["messages"]) == 2 and t2["messages"][1]["id"] != old


async def test_snippet_only_fallback_when_pages_blocked(make_api):
    api = await make_api(
        ssrf_allow_private=False
    )  # the fake web lives on 127.0.0.1 → every page blocked
    events, _ = await run_query(api)
    assert events[-1][1] == "done"
    assert any(n == "warning" and d["code"] == "snippets_only" for _, n, d in events)
    failed = [d for _, n, d in events if n == "source_update" and d["state"] == "failed"]
    assert (failed and "not allowed" in (failed[0]["reason"] or "").lower()) or "private" in (
        failed[0]["reason"] or ""
    ).lower()


def test_missing_api_key_is_actionable() -> None:
    from gleanwise.errors import LLMAuthError, classify_llm_exception

    exc = classify_llm_exception(
        RuntimeError(
            "The api_key client option must be set either by passing api_key to the client"
        )
    )
    assert isinstance(exc, LLMAuthError)
    assert exc.action == "open_settings"
    assert exc.hint
