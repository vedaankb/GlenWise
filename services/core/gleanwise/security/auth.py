# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Ved Buddaraju

"""Optional bearer-token authentication for the HTTP API."""

from __future__ import annotations

import hmac

from fastapi import Request

from gleanwise.config import Settings
from gleanwise.errors import Unauthorized


def require_token(request: Request) -> None:
    """FastAPI dependency. A no-op unless ``GLEANWISE_API_TOKEN`` is configured."""
    settings: Settings = request.app.state.svc.settings
    token = settings.api_token
    if not token:
        return
    header = request.headers.get("authorization", "")
    supplied = header[7:] if header.lower().startswith("bearer ") else ""
    if not supplied or not hmac.compare_digest(supplied.encode(), token.encode()):
        raise Unauthorized(
            "A valid API token is required.",
            hint="Send 'Authorization: Bearer <token>'. The token is set with GLEANWISE_API_TOKEN.",
        )
