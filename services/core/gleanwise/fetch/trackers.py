# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Ved Buddaraju

"""Tracker / ad host blocklist for the Playwright fetcher (D10).

Best-effort: blocks well-known analytics and ad hosts so a rendered page cannot phone
third parties. Not a substitute for a full EasyList.
"""

from __future__ import annotations

from urllib.parse import urlsplit

# Host suffixes (and exact hosts). Kept short and obvious; extend over time.
BLOCKED_SUFFIXES: tuple[str, ...] = (
    "doubleclick.net",
    "google-analytics.com",
    "googletagmanager.com",
    "googlesyndication.com",
    "googleadservices.com",
    "facebook.net",
    "facebook.com",
    "connect.facebook.net",
    "scorecardresearch.com",
    "quantserve.com",
    "hotjar.com",
    "mixpanel.com",
    "segment.io",
    "segment.com",
    "amplitude.com",
    "newrelic.com",
    "nr-data.net",
    "sentry.io",
    "clarity.ms",
    "adservice.google.com",
    "adsystem.com",
    "adnxs.com",
    "adsrvr.org",
    "taboola.com",
    "outbrain.com",
    "criteo.com",
    "criteo.net",
    "pubmatic.com",
    "openx.net",
    "rubiconproject.com",
    "moatads.com",
    "chartbeat.com",
    "parsely.com",
    "optimizely.com",
    "crazyegg.com",
    "mouseflow.com",
    "fullstory.com",
    "heap-api.com",
    "heapanalytics.com",
    "intercom.io",
    "intercomcdn.com",
    "zendesk.com",
    "zdassets.com",
)


def is_tracker_host(host: str) -> bool:
    h = (host or "").lower().rstrip(".")
    if not h:
        return False
    return any(h == suf or h.endswith("." + suf) for suf in BLOCKED_SUFFIXES)


def is_tracker_url(url: str) -> bool:
    try:
        host = urlsplit(url).hostname or ""
    except ValueError:
        return False
    return is_tracker_host(host)
