# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Ved Buddaraju

"""Egress package: local CONNECT gateway, activity log, Strict Local policy."""

from gleanwise.egress.gateway import EgressGateway
from gleanwise.egress.log import LOG, EgressEntry, EgressLog
from gleanwise.egress.policy import (
    assert_strict_local_embedder,
    assert_strict_local_llm,
    hostname_of,
    is_local_host,
    is_local_llm_endpoint,
    redact_pii,
    restore_pii,
)

__all__ = [
    "LOG",
    "EgressEntry",
    "EgressGateway",
    "EgressLog",
    "assert_strict_local_embedder",
    "assert_strict_local_llm",
    "hostname_of",
    "is_local_host",
    "is_local_llm_endpoint",
    "redact_pii",
    "restore_pii",
]
