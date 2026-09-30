# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Ved Buddaraju

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Request

from gleanwise.config import Settings
from gleanwise.pipeline.runtime import QueryRuntime
from gleanwise.security.auth import require_token
from gleanwise.services import Services


def get_svc(request: Request) -> Services:
    svc: Services = request.app.state.svc
    return svc


def get_rt(request: Request) -> QueryRuntime:
    rt: QueryRuntime = request.app.state.rt
    return rt


def get_settings_dep(request: Request) -> Settings:
    return get_svc(request).settings


SvcDep = Annotated[Services, Depends(get_svc)]
RtDep = Annotated[QueryRuntime, Depends(get_rt)]
Auth = Depends(require_token)

ERROR_RESPONSES = {
    401: {"description": "Missing or invalid API token"},
    422: {"description": "Invalid request"},
    429: {"description": "Server busy"},
}
