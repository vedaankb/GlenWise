# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Ved Buddaraju

"""Citation extraction and validation against the source table."""

from __future__ import annotations

import re

from gleanwise.models import Citation, Source
from gleanwise.util.text import truncate

# [1], [2][5], [1,2], [1, 2, 3]  — but not markdown links like [text](url) or footnote text.
_GROUP = re.compile(r"\[(\d{1,3}(?:\s*[,;]\s*\d{1,3})*)\](?!\()")


def _numbers(group: str) -> list[int]:
    return [int(x) for x in re.split(r"\s*[,;]\s*", group.strip())]


def finalize_answer(
    text: str, sources: dict[int, Source], excerpts: dict[int, str]
) -> tuple[str, list[Citation]]:
    """Remove markers that don't correspond to a known source; return the cleaned text + citations.

    Citations are ordered by first appearance. ``[1,2]`` is normalised to ``[1][2]``.
    """
    order: list[int] = []
    dropped = False

    def repl(m: re.Match[str]) -> str:
        nonlocal dropped
        all_nums = _numbers(m.group(1))
        nums = [n for n in all_nums if n in sources]
        dropped = dropped or len(nums) != len(all_nums)
        for n in nums:
            if n not in order:
                order.append(n)
        return "".join(f"[{n}]" for n in nums)

    cleaned = _GROUP.sub(repl, text)
    if dropped:  # tidy the gaps left by removed (hallucinated) markers
        cleaned = re.sub(r"[ \t]+([.,;:!?])", r"\1", cleaned)
        cleaned = re.sub(r"(?<=\S) {2,}", " ", cleaned)
    citations = [
        Citation(
            number=n,
            source_id=n,
            url=sources[n].url,
            title=sources[n].title,
            excerpt=truncate(excerpts.get(n, sources[n].snippet), 280),
        )
        for n in order
    ]
    return cleaned.strip(), citations
