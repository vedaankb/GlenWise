# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Ved Buddaraju

"""Structured logging with a per-query correlation id."""

from __future__ import annotations

import contextvars
import json
import logging
import sys
from datetime import UTC, datetime

query_id_var: contextvars.ContextVar[str] = contextvars.ContextVar("query_id", default="")


class _Filter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.query_id = query_id_var.get()
        return True


class _JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": datetime.fromtimestamp(record.created, UTC).isoformat(timespec="milliseconds"),
            "level": record.levelname.lower(),
            "logger": record.name,
            "msg": record.getMessage(),
        }
        if qid := getattr(record, "query_id", ""):
            payload["query_id"] = qid
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)


def configure_logging(*, json_logs: bool = False, level: str = "INFO") -> None:
    handler = logging.StreamHandler(sys.stderr)
    handler.addFilter(_Filter())
    if json_logs:
        handler.setFormatter(_JsonFormatter())
    else:
        handler.setFormatter(
            logging.Formatter("%(asctime)s %(levelname)-7s %(name)s %(message)s [%(query_id)s]")
        )
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(level)
    for noisy in (
        "httpx",
        "httpcore",
        "LiteLLM",
        "litellm",
        "asyncio",
        "hpack",
        "fastembed",
        "onnxruntime",
    ):
        logging.getLogger(noisy).setLevel(logging.WARNING)
