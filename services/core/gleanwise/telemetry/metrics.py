# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Ved Buddaraju

"""Prometheus metrics. One registry per process; exposed at GET /metrics (operator-guarded)."""

from __future__ import annotations

from prometheus_client import CollectorRegistry, Counter, Gauge, Histogram

REGISTRY = CollectorRegistry()

QUERIES = Counter(
    "gleanwise_queries_total", "Queries finished", ["mode", "status"], registry=REGISTRY
)
STAGE_SECONDS = Histogram(
    "gleanwise_stage_seconds",
    "Latency per pipeline stage",
    ["mode", "stage"],
    buckets=(0.05, 0.1, 0.25, 0.5, 1, 2, 4, 8, 16, 32, 64, 128),
    registry=REGISTRY,
)
TTFT = Histogram(
    "gleanwise_time_to_first_token_seconds",
    "Submit → first answer token",
    ["mode"],
    buckets=(0.25, 0.5, 1, 2, 3, 5, 8, 13, 21, 34, 60),
    registry=REGISTRY,
)
TOKENS = Counter("gleanwise_llm_tokens_total", "LLM tokens", ["kind"], registry=REGISTRY)
COST = Counter("gleanwise_llm_cost_usd_total", "Estimated LLM spend in USD", registry=REGISTRY)
FETCHES = Counter(
    "gleanwise_fetch_total", "Page fetches by outcome", ["outcome"], registry=REGISTRY
)
ACTIVE = Gauge("gleanwise_active_queries", "Queries currently running", registry=REGISTRY)
QUEUED = Gauge("gleanwise_queued_queries", "Queries waiting for a slot", registry=REGISTRY)
FEEDBACK = Counter("gleanwise_feedback_total", "Feedback by thumb", ["thumb"], registry=REGISTRY)
