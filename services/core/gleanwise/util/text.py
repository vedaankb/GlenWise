# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Ved Buddaraju

"""Small text helpers shared across the pipeline."""

from __future__ import annotations

import hashlib
import re
import unicodedata
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

_WORD = re.compile(r"\w+", re.UNICODE)
_STOP = frozenset(
    [
        "a",
        "an",
        "and",
        "are",
        "as",
        "at",
        "be",
        "by",
        "for",
        "from",
        "has",
        "have",
        "how",
        "i",
        "in",
        "is",
        "it",
        "its",
        "of",
        "on",
        "or",
        "that",
        "the",
        "this",
        "to",
        "was",
        "were",
        "what",
        "when",
        "where",
        "which",
        "who",
        "why",
        "will",
        "with",
        "do",
        "does",
        "did",
        "can",
        "could",
        "should",
        "would",
        "about",
    ]
)
_TRACKING = re.compile(r"^(utm_|mc_|fbclid|gclid|igshid|ref$|ref_src|spm$|yclid|_hs)", re.I)


def tokens(text: str) -> list[str]:
    return [t.lower() for t in _WORD.findall(text)]


def content_tokens(text: str, limit: int = 24) -> list[str]:
    """Distinct, non-stopword tokens in first-seen order."""
    seen: dict[str, None] = {}
    for tok in tokens(text):
        if tok in _STOP or (len(tok) < 2 and tok.isascii()):
            continue
        seen.setdefault(tok, None)
        if len(seen) >= limit:
            break
    return list(seen)


def fts_query(text: str, limit: int = 24) -> str | None:
    """Turn arbitrary user text into a *safe* FTS5 MATCH expression.

    Every term is double-quoted so FTS5 operators (``AND``, ``NEAR``, ``:``, ``-``, ``*``) in user
    text are treated as literals; terms are OR-ed and ranking is left to BM25.
    """
    terms = content_tokens(text, limit) or tokens(text)[:limit]
    if not terms:
        return None
    return " OR ".join('"' + t.replace('"', "") + '"' for t in terms)


def sha1_hex(*parts: str, length: int = 20) -> str:
    h = hashlib.sha1(usedforsecurity=False)
    for p in parts:
        h.update(p.encode("utf-8", "replace"))
        h.update(b"\x00")
    return h.hexdigest()[:length]


_TRACKING_LINK = re.compile(r"^(utm_|mc_|fbclid|gclid|igshid|yclid|_hs)", re.I)


def strip_tracking(url: str) -> str:
    """The URL the user will click: same page, without ``utm_*``-style tracking parameters."""
    try:
        parts = urlsplit(url.strip())
    except ValueError:
        return url
    if parts.scheme not in {"http", "https"} or not parts.query:
        return url
    kept = [
        (k, v)
        for k, v in parse_qsl(parts.query, keep_blank_values=True)
        if not _TRACKING_LINK.match(k)
    ]
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(kept), parts.fragment))


def canonicalize_url(url: str) -> str:
    """Stable URL identity: lowercase host, drop fragment + tracking params, sort the query."""
    try:
        parts = urlsplit(url.strip())
    except ValueError:
        return url
    if parts.scheme not in {"http", "https"}:
        return url
    host = (parts.hostname or "").lower()
    port = f":{parts.port}" if parts.port and parts.port not in (80, 443) else ""
    query = urlencode(
        sorted(
            (k, v)
            for k, v in parse_qsl(parts.query, keep_blank_values=True)
            if not _TRACKING.match(k)
        )
    )
    path = parts.path or "/"
    if path != "/" and path.endswith("/"):
        path = path.rstrip("/")
    return urlunsplit((parts.scheme, f"{host}{port}", path, query, ""))


def domain_of(url: str) -> str:
    try:
        host = urlsplit(url).hostname or ""
    except ValueError:
        return ""
    return host[4:] if host.startswith("www.") else host


def normalize_text(text: str) -> str:
    return unicodedata.normalize("NFKC", text)


def truncate(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[: max(0, limit - 1)].rstrip() + "…"


def approx_tokens(text: str) -> int:
    # ~4 chars/token for latin scripts, ~1.5 for CJK; good enough for budgeting.
    cjk = sum(1 for c in text if "\u3000" <= c <= "\u9fff")
    return max(1, (len(text) - cjk) // 4 + int(cjk / 1.5))
