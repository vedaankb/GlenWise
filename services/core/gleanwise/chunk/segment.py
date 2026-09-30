# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Ved Buddaraju

"""Heading-aware chunking with truthful offsets and deterministic IDs."""

from __future__ import annotations

import re
from dataclasses import dataclass

from gleanwise.models import Chunk
from gleanwise.util.text import approx_tokens, sha1_hex

_HEADING = re.compile(r"^(#{1,6})[ \t]+(.+?)[ \t]*$", re.MULTILINE)
_PARA = re.compile(r"\S(?:.|\n(?!\s*\n))*", re.UNICODE)
_SENT = re.compile(r"[^.!?。！？\n]+[.!?。！？]*\s*")
MIN_CHARS = 40


@dataclass
class _Unit:
    start: int
    end: int
    tokens: int


def _units(text: str, base: int, max_tokens: int) -> list[_Unit]:
    out: list[_Unit] = []
    for m in _PARA.finditer(text):
        s, e = base + m.start(), base + m.end()
        tok = approx_tokens(m.group())
        if tok <= max_tokens:
            out.append(_Unit(s, e, tok))
            continue
        # Oversized paragraph → sentences → hard word windows.
        for sm in _SENT.finditer(m.group()):
            piece = sm.group()
            if not piece.strip():
                continue
            ps, pe = s + sm.start(), s + sm.end()
            ptok = approx_tokens(piece)
            if ptok <= max_tokens:
                out.append(_Unit(ps, pe, ptok))
                continue
            words = list(re.finditer(r"\S+", piece))
            step = max(1, max_tokens // 2)
            for i in range(0, len(words), step):
                w = words[i : i + step]
                out.append(_Unit(ps + w[0].start(), ps + w[-1].end(), max(1, len(w) * 2)))
    return out


def chunk_document(
    text: str,
    *,
    url: str,
    doc_id: str,
    max_tokens: int = 320,
    overlap_tokens: int = 40,
) -> list[Chunk]:
    if not text.strip():
        return []
    headings = list(_HEADING.finditer(text))
    spans: list[tuple[str, int, int]] = []  # (heading_path, start, end)
    stack: list[tuple[int, str]] = []
    first = headings[0].start() if headings else len(text)
    if text[:first].strip():
        spans.append(("", 0, first))
    for i, h in enumerate(headings):
        level, title = len(h.group(1)), h.group(2).strip()
        while stack and stack[-1][0] >= level:
            stack.pop()
        stack.append((level, title))
        end = headings[i + 1].start() if i + 1 < len(headings) else len(text)
        spans.append((" > ".join(t for _, t in stack), h.start(), end))

    chunks: list[Chunk] = []
    for path, s, e in spans:
        units = _units(text[s:e], s, max_tokens)
        i = 0
        while i < len(units):
            j, total = i, 0
            while j < len(units) and (total + units[j].tokens <= max_tokens or j == i):
                total += units[j].tokens
                j += 1
            start, end = units[i].start, units[j - 1].end
            piece = text[start:end]
            if len(piece.strip()) >= MIN_CHARS or (not chunks and j >= len(units)):
                chunks.append(
                    Chunk(
                        id=sha1_hex(doc_id, str(start), piece),
                        doc_id=doc_id,
                        url=url,
                        heading_path=path,
                        text=piece,
                        start=start,
                        end=end,
                    )
                )
            if j >= len(units):
                break
            # Step back so consecutive chunks share ~overlap_tokens of trailing context.
            back, acc = j, 0
            while back > i + 1 and acc + units[back - 1].tokens <= overlap_tokens:
                acc += units[back - 1].tokens
                back -= 1
            i = back if back > i else j
    return chunks
