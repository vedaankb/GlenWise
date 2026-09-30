# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Ved Buddaraju

from __future__ import annotations

import json

from tests.conftest import run_query


# --- Host / Origin / token -------------------------------------------------------------------
async def test_dns_rebinding_host_rejected(api):
    r = await api.client.get("/livez", headers={"Host": "evil.example.com:8787"})
    assert r.status_code == 421 and r.json()["error"]["code"] == "forbidden_host"
    assert (await api.client.get("/livez", headers={"Host": "localhost:8787"})).status_code == 200
    assert (await api.client.get("/livez", headers={"Host": "127.0.0.1:8787"})).status_code == 200
    assert (await api.client.get("/livez", headers={"Host": "[::1]:8787"})).status_code == 200


async def test_csrf_cross_origin_post_rejected(api):
    hdr = {"Origin": "https://evil.example.com"}
    r = await api.client.post("/query", json={"query": "x"}, headers=hdr)
    assert r.status_code == 403 and r.json()["error"]["code"] == "forbidden_origin"
    r = await api.client.put("/settings", json={"llm_model": "evil"}, headers=hdr)
    assert r.status_code == 403
    assert (await api.client.get("/settings")).json()["llm_model"] == "openai/fake-model"
    # same-origin browsers and non-browser clients still work
    ok = await api.client.post(
        "/query", json={"query": "x"}, headers={"Origin": "http://localhost"}
    )
    assert ok.status_code == 202
    assert (await api.client.post("/query", json={"query": "x"})).status_code == 202


async def test_cors_only_for_allowed_origins(make_api):
    api = await make_api(allowed_origins=["https://blog.example.org"])
    good = await api.client.options(
        "/query",
        headers={
            "Origin": "https://blog.example.org",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type",
        },
    )
    assert good.headers.get("access-control-allow-origin") == "https://blog.example.org"
    assert "access-control-allow-credentials" not in good.headers
    bad = await api.client.options(
        "/query",
        headers={"Origin": "https://evil.example", "Access-Control-Request-Method": "POST"},
    )
    assert "access-control-allow-origin" not in bad.headers
    ok = await api.client.post(
        "/query", json={"query": "x"}, headers={"Origin": "https://blog.example.org"}
    )
    assert ok.status_code == 202


async def test_api_token_required_when_configured(make_api):
    api = await make_api(api_token="s3cret", operator_metrics=True)
    assert (await api.client.get("/livez")).status_code == 200  # probes stay open
    r = await api.client.get("/threads")
    assert r.status_code == 401 and r.json()["error"]["code"] == "unauthorized"
    assert (
        await api.client.get("/threads", headers={"Authorization": "Bearer nope"})
    ).status_code == 401
    assert (
        await api.client.get("/threads", headers={"Authorization": "Bearer s3cret"})
    ).status_code == 200
    assert (await api.client.get("/metrics")).status_code == 401
    assert (
        await api.client.get("/metrics", headers={"Authorization": "Bearer s3cret"})
    ).status_code == 200


async def test_server_profile_operator_endpoints_need_token(make_api):
    api = await make_api(profile="server", operator_metrics=True)
    assert (await api.client.get("/metrics")).status_code == 401
    assert (await api.client.get("/operator/traces")).status_code == 401


async def test_security_headers_present(api):
    r = await api.client.get("/livez")
    assert (
        r.headers["x-content-type-options"] == "nosniff"
        and r.headers["referrer-policy"] == "no-referrer"
    )


async def test_error_envelope_for_validation_and_405(api):
    r = await api.client.post("/query", json={"query": ""})
    assert r.status_code == 422 and r.json()["error"]["code"] == "bad_request"
    r = await api.client.delete("/livez")
    assert r.status_code == 405 and r.json()["error"]["code"] == "method_not_allowed"
    r = await api.client.post("/query", json={"query": "x" * 5000})
    assert r.status_code == 422 or r.status_code == 202


# --- settings ----------------------------------------------------------------------------------
async def test_settings_redacts_secrets_and_reports_locks(api):
    s = (await api.client.get("/settings")).json()
    assert "llm_api_key" not in s and s["llm_api_key_set"] is True and s["configured"] is True
    assert "llm_model" in s["env_locked"] and "locale" not in s["env_locked"]
    # a field fixed by the environment can't be changed from the browser, and says why
    r = await api.client.put("/settings", json={"llm_model": "openai/other"})
    assert (
        r.status_code == 409
        and r.json()["error"]["code"] == "conflict"
        and "GLEANWISE_" in r.json()["error"]["hint"]
    )
    ok = await api.client.put("/settings", json={"locale": "fr", "thread_retention_days": 7})
    assert ok.status_code == 200 and ok.json()["locale"] == "fr"
    path = api.svc.settings.settings_file
    assert json.loads(path.read_text())["locale"] == "fr"
    assert oct(path.stat().st_mode & 0o777) == "0o600"
    bad = await api.client.put("/settings", json={"searxng_url": "ftp://x"})
    assert bad.status_code in (409, 422)


async def test_env_locked_fields_cannot_be_overridden_by_ui(tmp_path, monkeypatch, stack):
    from gleanwise.config import Settings

    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "settings.json").write_text(
        json.dumps(
            {
                "llm_model": "from-ui",
                "embed_model": "ui-embed",
                "ssrf_allow_private": True,
                "api_token": "x",
            }
        )
    )
    monkeypatch.setenv("GLEANWISE_LLM_MODEL", "from-env")
    s = Settings(_env_file=None, data_dir=tmp_path / "data").overlay_ui_settings()
    assert s.llm_model == "from-env"  # env wins over the UI file
    assert s.embed_model == "ui-embed"  # UI fills fields env did not set
    assert s.ssrf_allow_private is False and s.api_token == ""  # non-UI keys are ignored


async def test_setup_test_reports_each_component(api):
    r = (await api.client.post("/setup/test", json={})).json()
    assert r["llm"]["ok"] and r["search"]["ok"]
    bad = (
        await api.client.post(
            "/setup/test",
            json={"llm_api_base": "http://127.0.0.1:9/v1", "searxng_url": "http://127.0.0.1:9"},
        )
    ).json()
    assert not bad["llm"]["ok"] and bad["llm"]["hint"]
    assert not bad["search"]["ok"]


async def test_health_endpoints(api):
    assert (await api.client.get("/livez")).json()["ok"] is True
    ready = (await api.client.get("/readyz")).json()
    assert {c["name"] for c in ready["components"]} >= {
        "storage",
        "search",
        "llm",
        "embeddings",
        "reranker",
    }
    assert ready["ok"] is True
    diag = (await api.client.get("/diagnostics")).json()
    assert any(c["name"] == "cache" for c in diag["components"])


# --- tools -----------------------------------------------------------------------------------
async def test_tools_search_fetch_retrieve(api):
    s = (await api.client.post("/search", json={"query": "heat pumps"})).json()
    assert s["results"] and s["results"][0]["id"] == 1
    url = s["results"][0]["url"]
    assert "utm_source" not in url  # outbound links never carry tracking parameters
    f = (await api.client.post("/fetch", json={"url": url, "max_chars": 500})).json()
    assert f["text"] and f["truncated"] is True
    rr = (
        await api.client.post(
            "/retrieve", json={"query": "coefficient of performance", "urls": [url]}
        )
    ).json()
    assert rr["chunks"] and "performance" in rr["chunks"][0]["text"].lower()
    empty = (await api.client.post("/search", json={"query": "zzznoresults"})).json()
    assert empty["results"] == [] and empty["warnings"]


async def test_fetch_is_conditional_and_cached(api):
    url = f"{api.stack.web_url}/p/heat-pumps-explained"
    await api.client.post("/fetch", json={"url": url})
    n = len(api.stack.web_state.hits)
    again = (await api.client.post("/fetch", json={"url": url})).json()
    assert (
        again["from_cache"] is True and len(api.stack.web_state.hits) == n
    )  # served from cache within TTL


async def test_favicon_proxy_validates_and_falls_back(api):
    assert (
        await api.client.get("/proxy/favicon", params={"domain": "not a domain"})
    ).status_code == 422
    r = await api.client.get("/proxy/favicon", params={"domain": "example.invalid"})
    assert r.status_code == 200 and r.headers["content-type"].startswith("image/svg+xml")
    assert "sandbox" in r.headers["content-security-policy"]


async def test_image_proxy_serves_rasters_and_refuses_svg_and_private(api, make_api):
    ok = await api.client.get("/proxy/image", params={"url": f"{api.stack.web_url}/img.png"})
    assert ok.status_code == 200 and ok.headers["content-type"] == "image/png"
    assert (
        ok.headers["x-content-type-options"] == "nosniff"
        and "sandbox" in ok.headers["content-security-policy"]
    )
    svg = await api.client.get("/proxy/image", params={"url": f"{api.stack.web_url}/img.svg"})
    assert svg.status_code == 422 and svg.json()["error"]["code"]
    strict = await make_api(ssrf_allow_private=False)
    blocked = await strict.client.get("/proxy/image", params={"url": "http://127.0.0.1:1/x.png"})
    assert blocked.status_code in (400, 403, 422) and "error" in blocked.json()
    authed = await make_api(api_token="s3cret")
    assert (
        await authed.client.get("/proxy/image", params={"url": "http://x.example/a.png"})
    ).status_code == 401


# --- export ---------------------------------------------------------------------------------
async def test_export_markdown_and_pdf(api):
    _, acc = await run_query(api)
    md = await api.client.get(f"/threads/{acc['thread_id']}/export", params={"format": "md"})
    assert (
        md.status_code == 200
        and "**Sources**" in md.text
        and "attachment" in md.headers["content-disposition"]
    )
    pdf = await api.client.get(f"/threads/{acc['thread_id']}/export", params={"format": "pdf"})
    assert pdf.content.startswith(b"%PDF") and len(pdf.content) > 1000


async def test_thread_crud_and_search(api):
    _, acc = await run_query(api)
    tid = acc["thread_id"]
    assert (
        await api.client.patch(f"/threads/{tid}", json={"title": "Renamed", "pinned": True})
    ).json()["ok"]
    listed = (await api.client.get("/threads", params={"q": "renamed"})).json()
    assert listed and listed[0]["pinned"] and listed[0]["title"] == "Renamed"
    assert (await api.client.delete(f"/threads/{tid}")).status_code == 200
    assert (await api.client.get(f"/threads/{tid}")).status_code == 404


async def test_feedback_and_traces_never_contain_raw_query(make_api):
    api = await make_api(operator_metrics=True)
    events, _ = await run_query(api, query="a very private question about heat pumps")
    qid = events[-1][2]["query_id"]
    await api.client.post("/feedback", json={"query_id": qid, "thumb": 1, "comment": "nice"})
    assert (await api.client.get("/operator/feedback")).json()[0]["thumb"] == 1
    traces = (await api.client.get("/operator/traces")).json()
    blob = json.dumps(traces)
    assert "private question" not in blob and traces[0]["query_sha"] and traces[0]["stages"]
    m = (await api.client.get("/metrics")).text
    assert 'gleanwise_queries_total{mode="quick",status="complete"}' in m


# --- OpenAI compatibility -------------------------------------------------------------------
async def test_openai_non_stream_shape(api):
    r = await api.client.post(
        "/v1/chat/completions",
        json={
            "model": "gleanwise-quick",
            "messages": [
                {"role": "system", "content": "Be terse."},
                {"role": "user", "content": "how do heat pumps work?"},
            ],
        },
    )
    assert r.status_code == 200
    j = r.json()
    assert j["object"] == "chat.completion" and j["id"].startswith("chatcmpl-")
    assert (
        j["choices"][0]["message"]["role"] == "assistant"
        and j["choices"][0]["finish_reason"] == "stop"
    )
    assert (
        j["usage"]["total_tokens"]
        == j["usage"]["prompt_tokens"] + j["usage"]["completion_tokens"]
        > 0
    )
    assert j["citations"] and "Be terse." in str(
        api.stack.llm_state.calls[-1]["messages"][0]["content"]
    )
    assert (await api.client.get("/threads")).json() == []  # OpenAI calls are stateless


async def test_openai_stream_shape_and_usage(api):
    r = await api.client.post(
        "/v1/chat/completions",
        json={
            "model": "gleanwise-quick",
            "stream": True,
            "stream_options": {"include_usage": True},
            "messages": [{"role": "user", "content": "how do heat pumps work?"}],
        },
    )
    lines = [ln[6:] for ln in r.text.split("\n") if ln.startswith("data: ")]
    assert lines[-1] == "[DONE]"
    chunks = [json.loads(x) for x in lines[:-1]]
    assert chunks[0]["choices"][0]["delta"]["role"] == "assistant"
    assert any(c["choices"] and c["choices"][0]["finish_reason"] == "stop" for c in chunks)
    assert chunks[-1]["choices"] == [] and chunks[-1]["usage"]["total_tokens"] > 0
    text = "".join(c["choices"][0]["delta"].get("content", "") for c in chunks if c["choices"])
    assert "[" in text and "\n\n---\n\n" not in text


async def test_openai_errors_use_openai_shape(make_api):
    api = await make_api(llm_model="")
    r = await api.client.post(
        "/v1/chat/completions",
        json={"model": "gleanwise-quick", "messages": [{"role": "user", "content": "hi"}]},
    )
    assert (
        r.status_code == 424
        and r.json()["error"]["code"] == "llm_not_configured"
        and "type" in r.json()["error"]
    )
    r = await api.client.post(
        "/v1/chat/completions",
        json={"model": "gleanwise-quick", "messages": [{"role": "assistant", "content": "hi"}]},
    )
    assert r.status_code == 422 and r.json()["error"]["type"] == "invalid_request_error"
    r = await api.client.post(
        "/v1/chat/completions",
        json={
            "model": "gleanwise-quick",
            "stream": True,
            "messages": [{"role": "user", "content": "hi"}],
        },
    )
    assert "error" in r.text and r.text.strip().endswith("[DONE]")
    models = (await api.client.get("/v1/models")).json()
    assert {m["id"] for m in models["data"]} == {
        "gleanwise-quick",
        "gleanwise-pro",
        "gleanwise-deep",
    }
