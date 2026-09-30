# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Ved Buddaraju

"""Application settings.

Precedence (highest first): explicit environment / .env  >  settings.json written by the
Settings UI  >  built-in defaults.  "Explicit" is decided with ``model_fields_set`` so that a
default value can never be mistaken for an operator override.
"""

from __future__ import annotations

import contextlib
import json
import os
import secrets
import tempfile
from pathlib import Path
from typing import Any, Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Fields the Settings UI is allowed to persist.  Anything else in settings.json is ignored so a
# tampered file cannot switch on dangerous flags (e.g. ssrf_allow_private).
UI_EDITABLE = (
    "llm_model",
    "llm_api_key",
    "llm_api_base",
    "embedder",
    "embed_model",
    "searxng_url",
    "thread_retention_days",
    "webhook_url",
    "locale",
    # Privacy suite (D5–D12)
    "strict_local",
    "redact_pii",
    "socks5_url",
    "socks5_for_search",
    "socks5_for_fetch",
    "local_hosts",
    "operator_metrics",
    "operator_webhooks",
    "egress_gateway",
)
SECRET_FIELDS = ("llm_api_key", "webhook_secret", "api_token")


def _csv(value: Any) -> Any:
    if isinstance(value, str):
        return [v.strip() for v in value.split(",") if v.strip()]
    return value


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="GLEANWISE_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        enable_decoding=False,  # lists are comma-separated, not JSON
    )

    # --- server -----------------------------------------------------------------------------
    host: str = "127.0.0.1"
    port: int = 8787
    data_dir: Path = Path("./data")
    profile: Literal["local", "server"] = "local"
    web_dir: str = ""  # directory containing the exported UI; auto-detected when empty
    log_json: bool = False

    # --- security ---------------------------------------------------------------------------
    api_token: str = ""  # when set, every API route requires "Authorization: Bearer <token>"
    allowed_origins: list[str] = Field(default_factory=list)  # extra CORS origins (widget hosts)
    allowed_hosts: list[str] = Field(default_factory=list)  # extra accepted Host headers
    ssrf_allow_private: bool = False  # tests / lab only; never exposed to the UI

    # --- models -----------------------------------------------------------------------------
    llm_model: str = ""
    llm_api_key: str = ""
    llm_api_base: str = ""
    llm_timeout_s: float = 90.0
    llm_first_token_timeout_s: float = 45.0
    embedder: Literal["local", "litellm", "hash"] = "local"
    embed_model: str = "BAAI/bge-small-en-v1.5"
    multilingual: bool = False  # picks multilingual embedder/reranker defaults
    reranker: Literal["cross-encoder", "lexical"] = "cross-encoder"
    reranker_model: str = "Xenova/ms-marco-MiniLM-L-6-v2"
    offline: bool = False  # never download models; fail clearly when missing
    locale: str = ""  # default UI/answer language hint (BCP-47), "" = auto

    # --- search / fetch ---------------------------------------------------------------------
    searxng_url: str = "http://127.0.0.1:8888"
    searxng_managed: bool = True
    searxng_bin: str = ""
    fetch_timeout_s: float = 12.0
    fetch_max_bytes: int = 3_000_000
    fetch_concurrency: int = 8
    fetch_per_host: int = 2
    fetch_ttl_s: int = 6 * 3600  # default freshness for cached pages
    fetch_ttl_news_s: int = 15 * 60
    respect_robots: bool = True
    browser_fallback: bool = True  # render JS-only pages with headless Chromium when installed
    quick_two_pass: bool = True  # Quick: answer from snippets first, then upgrade with full pages
    deep_max_rounds: int = 3
    user_agent: str = "GleanWise/0.2 (+https://github.com/gleanwise)"
    chunk_tokens: int = 320
    chunk_overlap_tokens: int = 40

    # --- limits -----------------------------------------------------------------------------
    max_concurrent_queries: int = 4
    max_queued_queries: int = 16
    quick_deadline_s: float = 45.0
    pro_deadline_s: float = 120.0
    deep_deadline_s: float = 480.0
    max_query_chars: int = 4000

    # --- storage / ops ----------------------------------------------------------------------
    thread_retention_days: int = 28
    trace_retention_days: int = 14
    database_url: str = ""
    webhook_url: str = ""
    webhook_secret: str = ""

    # --- privacy ---------------------------------------------------------------------------
    strict_local: bool = False  # D5: block non-local LLM / embed endpoints
    redact_pii: bool = False  # D9: opt-in redaction before cloud model calls
    egress_gateway: bool = True  # D3: route outbound HTTP(S) through the local CONNECT proxy
    socks5_url: str = ""  # D8: e.g. socks5://127.0.0.1:9050
    socks5_for_search: bool = False
    socks5_for_fetch: bool = False
    local_hosts: list[str] = Field(
        default_factory=list
    )  # extra LAN hosts allowed under Strict Local
    operator_metrics: bool = False  # D12: consent to expose /metrics locally
    operator_webhooks: bool = False  # D12: consent to push completed-answer webhooks

    ui_settings_path: Path | None = None

    @field_validator("allowed_origins", "allowed_hosts", "local_hosts", mode="before")
    @classmethod
    def _split(cls, value: Any) -> Any:
        return _csv(value)

    # --- helpers ----------------------------------------------------------------------------
    def resolved_data_dir(self) -> Path:
        path = self.data_dir.expanduser().resolve()
        path.mkdir(parents=True, exist_ok=True)
        with contextlib.suppress(OSError):
            path.chmod(0o700)
        (path / "cache").mkdir(exist_ok=True)
        return path

    def sqlite_path(self) -> Path:
        return self.resolved_data_dir() / "gleanwise.db"

    @property
    def settings_file(self) -> Path:
        return self.ui_settings_path or (self.resolved_data_dir() / "settings.json")

    def effective_embed_model(self) -> str:
        if (
            self.embedder == "local"
            and self.multilingual
            and "embed_model" not in self.model_fields_set
        ):
            return "intfloat/multilingual-e5-large"
        return self.embed_model

    def effective_reranker_model(self) -> str:
        if self.multilingual and "reranker_model" not in self.model_fields_set:
            return "jinaai/jina-reranker-v2-base-multilingual"
        return self.reranker_model

    def deadline_for(self, mode: str) -> float:
        return {
            "quick": self.quick_deadline_s,
            "pro": self.pro_deadline_s,
            "deep": self.deep_deadline_s,
        }.get(mode, self.pro_deadline_s)

    def overlay_ui_settings(self) -> Settings:
        """Return a copy with settings.json values applied to fields not set by the environment."""
        raw = read_ui_settings(self.settings_file)
        if not raw:
            return self
        merged: dict[str, Any] = {}
        for key in UI_EDITABLE:
            if key in self.model_fields_set:
                continue  # explicit env always wins
            value = raw.get(key)
            if value in (None, ""):
                continue
            merged[key] = value
        if not merged:
            return self
        return self.model_copy(update=merged)


def read_ui_settings(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def write_ui_settings(path: Path, updates: dict[str, Any]) -> None:
    """Atomically persist UI-editable settings with 0600 permissions."""
    current = read_ui_settings(path)
    for key, value in updates.items():
        if key not in UI_EDITABLE:
            continue
        if value is None:
            continue
        current[key] = value
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".settings-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(current, fh, indent=2, sort_keys=True)
        os.chmod(tmp, 0o600)
        os.replace(tmp, path)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(tmp)
        raise


def redact(settings: Settings) -> dict[str, Any]:
    """Settings safe to send to a browser: secrets replaced by presence flags."""
    data = settings.model_dump(mode="json", exclude={"ui_settings_path"})
    for key in SECRET_FIELDS:
        value = data.pop(key, "")
        data[f"{key}_set"] = bool(value)
    data["data_dir"] = str(settings.data_dir)
    return data


def generate_token() -> str:
    return secrets.token_urlsafe(32)


_settings: Settings | None = None


def get_settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = Settings().overlay_ui_settings()
    return _settings


def reload_settings() -> Settings:
    global _settings
    _settings = Settings().overlay_ui_settings()
    return _settings


def set_settings(settings: Settings) -> None:
    """Replace the process-wide settings (used by tests and the app factory)."""
    global _settings
    _settings = settings
