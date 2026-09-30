# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Ved Buddaraju

from __future__ import annotations

from fastapi import APIRouter, Request

from gleanwise import __version__
from gleanwise.api.deps import Auth, SvcDep
from gleanwise.config import UI_EDITABLE, Settings, write_ui_settings
from gleanwise.egress.policy import is_local_llm_endpoint
from gleanwise.errors import BadRequest, Conflict
from gleanwise.models import OkResponse, SettingsUpdate, SettingsView

router = APIRouter(tags=["settings"], dependencies=[Auth])


def view_of(s: Settings, locked: set[str], *, proxy_url: str = "") -> SettingsView:
    from gleanwise.privacy.keychain import keyring_available, load_secret

    key_set = bool(load_secret(s.llm_api_key) if s.llm_api_key else "")
    return SettingsView(
        llm_model=s.llm_model,
        llm_api_base=s.llm_api_base,
        llm_api_key_set=key_set,
        embedder=s.embedder,
        embed_model=s.effective_embed_model(),
        searxng_url=s.searxng_url,
        thread_retention_days=s.thread_retention_days,
        webhook_url=s.webhook_url if s.operator_webhooks else "",
        locale=s.locale,
        profile=s.profile,
        configured=bool(s.llm_model),
        auth_required=bool(s.api_token),
        env_locked=sorted(locked & set(UI_EDITABLE)),
        version=__version__,
        strict_local=s.strict_local,
        llm_local=is_local_llm_endpoint(s.llm_model, s.llm_api_base, list(s.local_hosts)),
        redact_pii=s.redact_pii,
        egress_gateway=s.egress_gateway,
        egress_proxy_url=proxy_url,
        socks5_url=s.socks5_url,
        socks5_for_search=s.socks5_for_search,
        socks5_for_fetch=s.socks5_for_fetch,
        local_hosts=list(s.local_hosts),
        operator_metrics=s.operator_metrics,
        operator_webhooks=s.operator_webhooks,
        keychain_available=keyring_available(),
    )


@router.get("/settings", response_model=SettingsView, summary="Current settings (secrets redacted)")
async def get_settings(request: Request, svc: SvcDep) -> SettingsView:
    gw = getattr(svc, "gateway", None)
    return view_of(
        svc.settings, request.app.state.env_locked, proxy_url=(gw.proxy_url or "") if gw else ""
    )


@router.put("/settings", response_model=SettingsView, summary="Update settings")
async def put_settings(body: SettingsUpdate, request: Request, svc: SvcDep) -> SettingsView:
    locked: set[str] = request.app.state.env_locked
    requested = body.model_dump(exclude_unset=True)
    blocked = sorted(k for k in requested if k in locked)
    if blocked:
        raise Conflict(
            f"{', '.join(blocked)} {'is' if len(blocked) == 1 else 'are'} fixed by the server's environment and can't be changed here.",
            hint="Change the GLEANWISE_* environment variable and restart, or ask your administrator.",
        )
    updates = requested
    for url_key in ("llm_api_base", "searxng_url", "webhook_url", "socks5_url"):
        val = updates.get(url_key)
        if not val:
            continue
        ok_prefixes = (
            ("http://", "https://") if url_key != "socks5_url" else ("socks5://", "socks5h://")
        )
        if not str(val).startswith(ok_prefixes):
            raise BadRequest(f"{url_key} must start with {' or '.join(ok_prefixes)}")
    if updates.get("webhook_url") and not (
        updates.get("operator_webhooks", svc.settings.operator_webhooks)
    ):
        raise BadRequest(
            "Webhooks are off until you enable them under Privacy.",
            hint="Turn on “Allow webhooks” in Settings → Privacy, then save the URL.",
            action="open_settings",
        )
    # Store API keys in the OS keychain when available (D7).
    if updates.get("llm_api_key"):
        from gleanwise.privacy.keychain import store_secret

        updates["llm_api_key"] = store_secret("llm_api_key", updates["llm_api_key"])
    write_ui_settings(svc.settings.settings_file, updates)
    new = svc.settings.model_copy(update=updates)
    await svc.apply_settings(new)
    gw = getattr(svc, "gateway", None)
    return view_of(new, locked, proxy_url=(gw.proxy_url or "") if gw else "")


@router.post(
    "/data/clear-cache", response_model=OkResponse, summary="Forget cached pages and embeddings"
)
async def clear_cache(svc: SvcDep) -> OkResponse:
    await svc.store.clear_index()
    return OkResponse()


@router.post(
    "/data/wipe", response_model=OkResponse, summary="Delete all conversations, feedback and traces"
)
async def wipe(svc: SvcDep) -> OkResponse:
    await svc.store.wipe_user_data()
    return OkResponse()
