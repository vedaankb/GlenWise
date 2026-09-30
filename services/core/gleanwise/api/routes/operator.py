# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Ved Buddaraju

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, Request, Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from gleanwise.api.deps import Auth, SvcDep
from gleanwise.errors import Forbidden, Unauthorized
from gleanwise.models import FeedbackOut, FeedbackRequest, OkResponse
from gleanwise.security.auth import require_token
from gleanwise.telemetry import metrics

router = APIRouter()


def require_operator(request: Request) -> None:
    """Operator endpoints expose usage data. Require consent (D12) and a token on server profile."""
    settings = request.app.state.svc.settings
    if not settings.operator_metrics:
        raise Forbidden(
            "Metrics and operator exports are off.",
            hint="Enable them under Settings → Privacy (you will be asked to confirm).",
            action="open_settings",
        )
    if settings.profile == "server" and not settings.api_token:
        raise Unauthorized(
            "Operator endpoints are disabled until an API token is configured.",
            hint="Set GLEANWISE_API_TOKEN to enable /metrics and /operator/*.",
        )
    require_token(request)


@router.post(
    "/feedback",
    response_model=OkResponse,
    tags=["feedback"],
    dependencies=[Auth],
    summary="Thumbs up/down on an answer",
)
async def feedback(body: FeedbackRequest, svc: SvcDep) -> OkResponse:
    await svc.store.add_feedback(body.query_id, body.thumb, body.comment)
    metrics.FEEDBACK.labels(str(body.thumb)).inc()
    return OkResponse()


@router.get(
    "/operator/feedback",
    response_model=list[FeedbackOut],
    tags=["operator"],
    dependencies=[Depends(require_operator)],
)
async def list_feedback(
    svc: SvcDep, limit: Annotated[int, Query(ge=1, le=1000)] = 200
) -> list[FeedbackOut]:
    return await svc.store.list_feedback(limit)


@router.get(
    "/operator/traces",
    response_model=list[dict[str, Any]],
    tags=["operator"],
    dependencies=[Depends(require_operator)],
    summary="Recent query traces (no raw queries)",
)
async def list_traces(
    svc: SvcDep, limit: Annotated[int, Query(ge=1, le=1000)] = 100
) -> list[dict[str, Any]]:
    return await svc.store.list_traces(limit)


@router.get(
    "/metrics",
    tags=["operator"],
    dependencies=[Depends(require_operator)],
    response_class=Response,
    summary="Prometheus metrics",
)
async def prometheus() -> Response:
    return Response(generate_latest(metrics.REGISTRY), media_type=CONTENT_TYPE_LATEST)
