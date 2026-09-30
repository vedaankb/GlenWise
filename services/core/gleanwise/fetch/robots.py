# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Ved Buddaraju

"""robots.txt cache with TTL and bounded size."""

from __future__ import annotations

import time
from collections import OrderedDict
from urllib.parse import urlsplit

from protego import Protego

from gleanwise.errors import GleanWiseError
from gleanwise.fetch.http import SafeHTTP

TTL_S = 3600.0
MAX_ENTRIES = 512


class RobotsCache:
    def __init__(self, http: SafeHTTP, user_agent: str) -> None:
        self._http = http
        self._ua = user_agent
        self._cache: OrderedDict[str, tuple[float, Protego | None]] = OrderedDict()

    async def allowed(self, url: str) -> bool:
        parts = urlsplit(url)
        origin = f"{parts.scheme}://{parts.netloc}"
        now = time.monotonic()
        hit = self._cache.get(origin)
        if hit is None or now - hit[0] > TTL_S:
            rules = await self._load(origin)
            self._cache[origin] = (now, rules)
            self._cache.move_to_end(origin)
            while len(self._cache) > MAX_ENTRIES:
                self._cache.popitem(last=False)
        else:
            rules = hit[1]
        if rules is None:
            return True
        return bool(rules.can_fetch(url, self._ua) or rules.can_fetch(url, "*"))

    async def _load(self, origin: str) -> Protego | None:
        try:
            res = await self._http.get(
                f"{origin}/robots.txt", max_bytes=500_000, timeout=5.0, accept_types=("text/",)
            )
        except GleanWiseError:
            return None  # unreachable robots.txt ⇒ no restrictions (RFC 9309 §2.3.1.4)
        if res.status >= 500:
            return Protego.parse("User-agent: *\nDisallow: /")  # server error ⇒ assume disallow
        if res.status >= 400 or not res.body:
            return None
        return Protego.parse(res.body.decode("utf-8", "replace"))
