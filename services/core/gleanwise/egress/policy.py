# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Ved Buddaraju

"""Egress policy: what counts as local, and Strict Local enforcement."""

from __future__ import annotations

import ipaddress
import re
from urllib.parse import urlsplit

from gleanwise.errors import BadRequest

_LOOPBACK = {"localhost", "127.0.0.1", "::1", "0.0.0.0"}  # noqa: S104 — identifying locals only
_LOCAL_SCHEMES = {"ollama", "ollama_chat", "huggingface"}  # LiteLLM local providers by prefix


def hostname_of(url_or_host: str) -> str:
    raw = (url_or_host or "").strip()
    if not raw:
        return ""
    if "://" not in raw and "/" not in raw and ":" in raw and not raw.startswith("["):
        # host:port
        return raw.rsplit(":", 1)[0].lower()
    if "://" not in raw:
        return raw.split("/")[0].split(":")[0].lower()
    return (urlsplit(raw).hostname or "").lower()


def is_local_host(host: str, extra: list[str] | None = None) -> bool:
    host = (host or "").lower().strip().rstrip(".")
    if not host:
        return False
    if host in _LOOPBACK or host.endswith(".localhost") or host.endswith(".local"):
        return True
    try:
        ip = ipaddress.ip_address(host)
        return bool(ip.is_loopback or ip.is_link_local)
    except ValueError:
        pass
    for allowed in extra or []:
        a = allowed.lower().strip()
        if not a:
            continue
        if host == a or host == hostname_of(a) or host.endswith("." + a):
            return True
    return False


def is_local_llm_endpoint(model: str, api_base: str, extra_hosts: list[str] | None = None) -> bool:
    """True when the model call cannot leave the machine (or an allowlisted LAN host)."""
    m = (model or "").strip().lower()
    for prefix in _LOCAL_SCHEMES:
        if m.startswith(prefix + "/"):
            # Still honour api_base if set — an ollama_chat model pointed at a remote base is remote.
            if not api_base:
                return True
            break
    host = hostname_of(api_base) if api_base else ""
    if not host and m.startswith(("ollama/", "ollama_chat/")):
        return True
    return is_local_host(host, extra_hosts) if host else False


def assert_strict_local_llm(model: str, api_base: str, extra_hosts: list[str]) -> None:
    if is_local_llm_endpoint(model, api_base, extra_hosts):
        return
    raise BadRequest(
        "Strict Local is on: this model endpoint is not on this machine.",
        hint="Use a local server (Ollama, LM Studio, …) or turn off Strict Local in Settings → Privacy.",
        action="open_settings",
    )


def assert_strict_local_embedder(embedder: str, api_base: str, extra_hosts: list[str]) -> None:
    if embedder in {"local", "hash"}:
        return
    host = hostname_of(api_base)
    if host and is_local_host(host, extra_hosts):
        return
    raise BadRequest(
        "Strict Local is on: cloud embeddings are blocked.",
        hint="Switch the embedder to Local in Settings, or turn off Strict Local.",
        action="open_settings",
    )


_EMAIL = re.compile(r"\b[A-Z0-9._%+\-]+@[A-Z0-9.\-]+\.[A-Z]{2,}\b", re.I)
_PHONE = re.compile(
    r"(?<!\w)(?:\+?\d{1,3}[\s\-.]?)?(?:\(?\d{2,4}\)?[\s\-.]?)?\d{3,4}[\s\-.]?\d{3,4}(?!\w)"
)
_SSN = re.compile(r"\b\d{3}-\d{2}-\d{4}\b")
_CARD = re.compile(r"\b(?:\d[ -]*?){13,19}\b")


def redact_pii(text: str) -> tuple[str, dict[str, str]]:
    """Replace emails, phones, SSN-shaped and card-shaped numbers with placeholders.

    Returns (redacted_text, mapping placeholder → original) so the answer can be restored.
    """
    mapping: dict[str, str] = {}
    counters = {"EMAIL": 0, "PHONE": 0, "ID": 0, "CARD": 0}

    def _sub(pattern: re.Pattern[str], kind: str, s: str) -> str:
        def repl(m: re.Match[str]) -> str:
            counters[kind] += 1
            token = f"[{kind}_{counters[kind]}]"
            mapping[token] = m.group(0)
            return token

        return pattern.sub(repl, s)

    out = text
    out = _sub(_EMAIL, "EMAIL", out)
    out = _sub(_SSN, "ID", out)
    out = _sub(_CARD, "CARD", out)
    out = _sub(_PHONE, "PHONE", out)
    return out, mapping


def restore_pii(text: str, mapping: dict[str, str]) -> str:
    if not mapping:
        return text
    # Longest first so EMAIL_10 is not partially eaten by EMAIL_1
    for token in sorted(mapping, key=len, reverse=True):
        text = text.replace(token, mapping[token])
    return text
