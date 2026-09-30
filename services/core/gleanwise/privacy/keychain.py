# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Ved Buddaraju

"""OS keychain helper for BYOK secrets (D7).

Uses the ``keyring`` package when available; falls back to the existing 0600 settings.json
so installs without keyring keep working. Values stored in the keychain are referenced from
settings.json as ``keychain:<service>`` so the file never holds the raw secret.
"""

from __future__ import annotations

import logging
from typing import Any

log = logging.getLogger(__name__)

SERVICE = "gleanwise"
PREFIX = "keychain:"


def keyring_available() -> bool:
    try:
        import keyring  # noqa: F401

        return True
    except Exception:
        return False


def store_secret(name: str, value: str) -> str:
    """Persist ``value`` under ``name`` and return the settings.json placeholder."""
    if not value:
        return ""
    try:
        import keyring

        keyring.set_password(SERVICE, name, value)
        return f"{PREFIX}{name}"
    except Exception as exc:
        log.info("keychain unavailable (%s); keeping secret in settings.json", exc)
        return value


def load_secret(ref: str) -> str:
    """Resolve a settings value that may be a keychain reference."""
    if not ref:
        return ""
    if not ref.startswith(PREFIX):
        return ref
    name = ref[len(PREFIX) :]
    try:
        import keyring

        return keyring.get_password(SERVICE, name) or ""
    except Exception as exc:
        log.warning("could not read %s from keychain: %s", name, exc)
        return ""


def delete_secret(name: str) -> None:
    try:
        import keyring

        keyring.delete_password(SERVICE, name)
    except Exception:
        pass


def materialize_secrets(data: dict[str, Any], fields: tuple[str, ...]) -> dict[str, Any]:
    """Return a copy with keychain refs resolved to plaintext (in memory only)."""
    out = dict(data)
    for f in fields:
        if f in out and isinstance(out[f], str):
            out[f] = load_secret(out[f])
    return out
