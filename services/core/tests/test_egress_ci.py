# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Ved Buddaraju

"""CI egress allowlist: a query against the fake stack must only touch expected hosts (D4)."""

from __future__ import annotations

import pytest

from gleanwise.egress.log import LOG


@pytest.mark.asyncio
async def test_query_egress_hosts_are_allowlisted(make_api):
    """After one answer, every logged host must be loopback or the fake stack."""
    LOG.clear()
    api = await make_api(egress_gateway=True)

    r = await api.client.post("/query", json={"query": "how do heat pumps work", "mode": "quick"})
    assert r.status_code in {200, 202}, r.text
    qid = r.json()["query_id"]
    async with api.client.stream("GET", f"/stream/{qid}") as stream:
        async for _ in stream.aiter_lines():
            pass

    activity = await api.client.get("/privacy/egress")
    assert activity.status_code == 200
    entries = activity.json()["entries"]

    # Fake stack listens on 127.0.0.1; gateway itself is loopback.
    allowed = {"127.0.0.1", "localhost", "::1"}
    unexpected = [
        e for e in entries if e.get("status") not in {"blocked"} and e["host"] not in allowed
    ]
    assert not unexpected, f"Unexpected egress hosts: {unexpected}"
    assert entries, "expected some egress activity for a completed query"
