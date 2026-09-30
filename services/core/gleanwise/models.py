# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Ved Buddaraju

"""Domain and API models. These are the single source for the generated OpenAPI/TS types."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class Mode(str, Enum):
    quick = "quick"
    pro = "pro"
    deep = "deep"


class Focus(str, Enum):
    general = "general"
    academic = "academic"
    news = "news"
    social = "social"


FOCUS_TO_SEARXNG: dict[Focus, str] = {
    Focus.general: "general",
    Focus.academic: "science",
    Focus.news: "news",
    Focus.social: "social media",
}


# --------------------------------------------------------------------------------------------
# Retrieval domain
# --------------------------------------------------------------------------------------------
class Source(BaseModel):
    id: int
    url: str
    title: str = ""
    snippet: str = ""
    domain: str = ""
    favicon: str | None = None
    published_at: str | None = None
    engines: list[str] = Field(default_factory=list)
    used_in_answer: bool = False
    state: Literal["found", "reading", "read", "failed", "skipped"] = "found"


class Chunk(BaseModel):
    id: str
    doc_id: str
    url: str
    heading_path: str = ""
    text: str
    start: int = 0
    end: int = 0
    embedding_model: str | None = None
    dim: int | None = None
    score: float | None = None


class Document(BaseModel):
    id: str
    url: str
    canonical_url: str
    title: str = ""
    content_type: str = "text/html"
    etag: str | None = None
    last_modified: str | None = None
    fetched_at: datetime | None = None
    expires_at: datetime | None = None
    ttl_class: str = "default"
    text: str = ""


class Citation(BaseModel):
    number: int
    source_id: int | None = None
    chunk_id: str | None = None
    url: str
    title: str = ""
    excerpt: str = ""


class Turn(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(max_length=20000)


# --------------------------------------------------------------------------------------------
# API requests
# --------------------------------------------------------------------------------------------
class QueryRequest(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={"examples": [{"query": "How do heat pumps work?"}]}
    )

    query: str = Field(min_length=1, max_length=8000)
    thread_id: str | None = None
    mode: Mode = Mode.quick
    focus: Focus = Focus.general
    model: str | None = None
    locale: str | None = Field(default=None, max_length=35)
    instructions: str | None = Field(default=None, max_length=2000)
    history: list[Turn] | None = Field(default=None, max_length=40)
    persist: bool = True
    private: bool = False  # D6: in-memory only — no history, cache, traces, webhooks
    draft: bool = True  # Quick: stream a snippet-based draft before the full-page answer
    regenerate_message_id: str | None = None


class SearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=2000)
    focus: Focus = Focus.general
    limit: int = Field(default=10, ge=1, le=30)
    locale: str | None = None


class FetchRequest(BaseModel):
    url: str = Field(max_length=4000)
    max_chars: int = Field(default=20000, ge=200, le=200000)


class RetrieveRequest(BaseModel):
    query: str = Field(min_length=1, max_length=2000)
    limit: int = Field(default=8, ge=1, le=40)
    urls: list[str] | None = None


class FeedbackRequest(BaseModel):
    query_id: str
    thumb: int = Field(ge=-1, le=1)
    comment: str | None = Field(default=None, max_length=2000)


class SettingsUpdate(BaseModel):
    llm_model: str | None = Field(default=None, max_length=200)
    llm_api_key: str | None = Field(default=None, max_length=500)
    llm_api_base: str | None = Field(default=None, max_length=500)
    embedder: Literal["local", "litellm", "hash"] | None = None
    embed_model: str | None = Field(default=None, max_length=200)
    searxng_url: str | None = Field(default=None, max_length=500)
    thread_retention_days: int | None = Field(default=None, ge=0, le=3650)
    webhook_url: str | None = Field(default=None, max_length=500)
    locale: str | None = Field(default=None, max_length=35)
    strict_local: bool | None = None
    redact_pii: bool | None = None
    egress_gateway: bool | None = None
    socks5_url: str | None = Field(default=None, max_length=500)
    socks5_for_search: bool | None = None
    socks5_for_fetch: bool | None = None
    local_hosts: list[str] | None = None
    operator_metrics: bool | None = None
    operator_webhooks: bool | None = None


class ThreadUpdate(BaseModel):
    title: str | None = Field(default=None, max_length=200)
    pinned: bool | None = None


class SetupTestRequest(BaseModel):
    llm_model: str | None = None
    llm_api_key: str | None = None
    llm_api_base: str | None = None
    searxng_url: str | None = None


# --------------------------------------------------------------------------------------------
# API responses
# --------------------------------------------------------------------------------------------
class QueryAccepted(BaseModel):
    query_id: str
    thread_id: str
    stream_url: str


class QueryStatus(BaseModel):
    query_id: str
    thread_id: str
    status: Literal["queued", "running", "complete", "error", "cancelled"]
    mode: Mode
    last_event_id: int = 0


class HealthComponent(BaseModel):
    name: str
    ok: bool
    detail: str = ""
    hint: str | None = None
    action: str | None = None


class HealthResponse(BaseModel):
    ok: bool
    version: str
    components: list[HealthComponent]


class LiveResponse(BaseModel):
    ok: bool = True
    version: str


class ThreadSummary(BaseModel):
    id: str
    title: str
    pinned: bool = False
    created_at: datetime
    updated_at: datetime
    mode: Mode | None = None


class MessageOut(BaseModel):
    id: str
    thread_id: str
    role: Literal["user", "assistant"]
    content: str
    citations: list[Citation] = Field(default_factory=list)
    mode: Mode | None = None
    focus: Focus | None = None
    sources: list[Source] = Field(default_factory=list)
    created_at: datetime | None = None
    query_id: str | None = None
    research_summary: str | None = None
    research_log: list[dict[str, Any]] | None = None
    follow_ups: list[str] = Field(default_factory=list)


class ThreadDetail(BaseModel):
    id: str
    title: str
    pinned: bool = False
    created_at: datetime
    updated_at: datetime
    messages: list[MessageOut]


class SearchResponse(BaseModel):
    query: str
    results: list[Source]
    warnings: list[str] = Field(default_factory=list)


class FetchResponse(BaseModel):
    url: str
    final_url: str
    title: str = ""
    text: str
    truncated: bool = False
    from_cache: bool = False


class RetrievedChunk(BaseModel):
    chunk_id: str
    url: str
    title: str = ""
    heading_path: str = ""
    text: str
    score: float


class RetrieveResponse(BaseModel):
    query: str
    chunks: list[RetrievedChunk]


class SettingsView(BaseModel):
    """Redacted settings for the browser. Secrets are reported only as ``*_set`` booleans."""

    llm_model: str = ""
    llm_api_base: str = ""
    llm_api_key_set: bool = False
    embedder: str = "local"
    embed_model: str = ""
    searxng_url: str = ""
    thread_retention_days: int = 28
    webhook_url: str = ""
    locale: str = ""
    profile: str = "local"
    configured: bool = False
    auth_required: bool = False
    env_locked: list[str] = Field(default_factory=list)
    version: str = ""
    # Privacy
    strict_local: bool = False
    llm_local: bool = (
        False  # True when the configured model cannot leave this machine / allowlisted LAN
    )
    redact_pii: bool = False
    egress_gateway: bool = True
    egress_proxy_url: str = ""
    socks5_url: str = ""
    socks5_for_search: bool = False
    socks5_for_fetch: bool = False
    local_hosts: list[str] = Field(default_factory=list)
    operator_metrics: bool = False
    operator_webhooks: bool = False
    keychain_available: bool = False


class SetupTestResult(BaseModel):
    llm: HealthComponent
    search: HealthComponent
    embeddings: HealthComponent


class EgressEvent(BaseModel):
    ts: float
    host: str
    port: int
    purpose: str
    bytes_in: int = 0
    bytes_out: int = 0
    status: str = "ok"
    detail: str = ""


class EgressActivity(BaseModel):
    gateway: str = ""  # proxy URL or "direct"
    gateway_status: str = ""
    entries: list[EgressEvent] = Field(default_factory=list)


class DataFlowInfo(BaseModel):
    """Per-answer data-flow summary (D11). Built from request + settings, no extra egress."""

    search: bool = True
    pages_fetched: int = 0
    model: str = ""
    model_local: bool = False
    redaction: bool = False
    private: bool = False
    proxy: bool = False
    socks5: bool = False
    strict_local: bool = False


class ErrorBody(BaseModel):
    code: str
    message: str
    hint: str | None = None
    action: str | None = None
    retryable: bool = False


class ErrorResponse(BaseModel):
    error: ErrorBody


class OkResponse(BaseModel):
    ok: bool = True


class FeedbackOut(BaseModel):
    query_id: str
    thumb: int
    comment: str | None = None
    created_at: datetime


# --------------------------------------------------------------------------------------------
# SSE event payloads (documented in OpenAPI via /schema/events; consumed by generated TS types)
# --------------------------------------------------------------------------------------------
class _Event(BaseModel):
    """Always fully populated on the wire, so the schema marks defaulted fields as required."""

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)


class PlanEvent(_Event):
    steps: list[str]
    mode: Mode
    rewritten_query: str | None = None
    subqueries: list[str] = Field(default_factory=list)


class SourcesEvent(_Event):
    sources: list[Source]


class SourceUpdateEvent(_Event):
    id: int
    state: Literal["found", "reading", "read", "failed", "skipped"]
    reason: str | None = None


class AnswerDeltaEvent(_Event):
    text: str
    draft: bool = False  # True while streaming a quick snippet-based draft that may be replaced


class AnswerUpgradeEvent(_Event):
    """The draft answer is being replaced by one written from full pages. Clear and re-stream."""

    reason: str = "full_pages"


class AnswerCompleteEvent(_Event):
    text: str
    citations: list[Citation] = Field(default_factory=list)


class FollowUpsEvent(_Event):
    questions: list[str]


class ReasoningDeltaEvent(_Event):
    text: str
    round: int | None = None


class VisitEvent(_Event):
    source_id: int
    url: str
    title: str = ""
    round: int | None = None


class WarningEvent(_Event):
    code: str
    message: str


class UsageInfo(_Event):
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cost_usd: float | None = None


class DoneEvent(_Event):
    query_id: str
    thread_id: str
    message_id: str | None = None
    status: Literal["complete", "cancelled"] = "complete"
    answer: str = ""
    citations: list[Citation] = Field(default_factory=list)
    sources: list[Source] = Field(default_factory=list)
    follow_ups: list[str] = Field(default_factory=list)
    usage: UsageInfo = Field(default_factory=UsageInfo)
    duration_ms: int = 0
    research_summary: str | None = None
    data_flow: DataFlowInfo | None = None


class EventCatalog(BaseModel):
    """Union of every event a query stream can emit, keyed by SSE ``event:`` name."""

    plan: PlanEvent | None = None
    sources: SourcesEvent | None = None
    source_update: SourceUpdateEvent | None = None
    answer_delta: AnswerDeltaEvent | None = None
    answer_upgrade: AnswerUpgradeEvent | None = None
    answer_complete: AnswerCompleteEvent | None = None
    follow_ups: FollowUpsEvent | None = None
    reasoning_delta: ReasoningDeltaEvent | None = None
    visit: VisitEvent | None = None
    warning: WarningEvent | None = None
    done: DoneEvent | None = None
    error: ErrorBody | None = None
