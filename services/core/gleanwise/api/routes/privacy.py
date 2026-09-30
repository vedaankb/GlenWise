# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Ved Buddaraju

"""Privacy / egress introspection routes."""

from __future__ import annotations

from fastapi import APIRouter

from gleanwise.api.deps import Auth, SvcDep
from gleanwise.egress.log import LOG
from gleanwise.models import EgressActivity, EgressEvent, OkResponse
from gleanwise.privacy.keychain import keyring_available

router = APIRouter(tags=["privacy"], dependencies=[Auth])


@router.get("/privacy/egress", response_model=EgressActivity, summary="Recent outbound connections")
async def egress_activity(svc: SvcDep) -> EgressActivity:
    gw = getattr(svc, "gateway", None)
    return EgressActivity(
        gateway=(gw.proxy_url if gw and gw.proxy_url else "direct"),
        gateway_status=(gw.status if gw else "disabled"),
        entries=[EgressEvent(**e) for e in LOG.recent(200)],
    )


@router.post("/privacy/egress/clear", response_model=OkResponse, summary="Clear the egress log")
async def clear_egress() -> OkResponse:
    LOG.clear()
    return OkResponse()


@router.get("/privacy/status", summary="Privacy feature flags currently in effect")
async def privacy_status(svc: SvcDep) -> dict:
    s = svc.settings
    gw = getattr(svc, "gateway", None)
    return {
        "strict_local": s.strict_local,
        "redact_pii": s.redact_pii,
        "egress_gateway": s.egress_gateway,
        "egress_proxy_url": (gw.proxy_url if gw else None),
        "socks5_configured": bool(s.socks5_url),
        "socks5_for_search": s.socks5_for_search,
        "socks5_for_fetch": s.socks5_for_fetch,
        "operator_metrics": s.operator_metrics,
        "operator_webhooks": s.operator_webhooks,
        "keychain_available": keyring_available(),
        "local_hosts": list(s.local_hosts),
    }
