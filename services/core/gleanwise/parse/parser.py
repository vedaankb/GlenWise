# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Ved Buddaraju

"""Content extraction: HTML (readability + fallback) and PDF → Markdown-ish text + metadata."""

from __future__ import annotations

import io
import json
import re
from dataclasses import dataclass
from typing import Any

from bs4 import BeautifulSoup, Tag, UnicodeDammit

_BOILERPLATE = [
    "script",
    "style",
    "noscript",
    "nav",
    "footer",
    "header",
    "aside",
    "form",
    "svg",
    "iframe",
]
_BLOCKS = ["h1", "h2", "h3", "h4", "h5", "h6", "p", "li", "pre", "blockquote", "tr", "figcaption"]
MAX_PDF_PAGES = 40


@dataclass
class ParsedPage:
    text: str
    title: str = ""
    lang: str | None = None
    published_at: str | None = None


def decode_body(body: bytes, declared: str | None = None) -> str:
    dammit = UnicodeDammit(body, known_definite_encodings=[declared] if declared else [])
    return dammit.unicode_markup or body.decode("utf-8", "replace")


def parse_html(html: str, url: str = "") -> ParsedPage:
    if not html or not html.strip():
        return ParsedPage(text="")
    meta_soup = BeautifulSoup(html, "lxml")
    title = _title(meta_soup)
    lang = (meta_soup.html.get("lang") if meta_soup.html else None) or None
    if isinstance(lang, list):
        lang = lang[0]
    published = _published(meta_soup)

    text = ""
    try:
        from readability import Document

        summary = Document(html).summary(html_partial=True)
        text = _to_markdown(summary)
    except Exception:
        text = ""
    # Readability sometimes over-prunes (docs, wikis, tables); fall back to the whole body.
    if len(text) < 400:
        fallback = _to_markdown(html)
        if len(fallback) > len(text):
            text = fallback
    if title and title.lower() not in text[:300].lower():
        text = f"# {title}\n\n{text}"
    return ParsedPage(text=text.strip(), title=title, lang=lang, published_at=published)


def parse_pdf(body: bytes) -> ParsedPage:
    try:
        from pypdf import PdfReader

        reader = PdfReader(io.BytesIO(body))
        pages: list[str] = []
        for page in reader.pages[:MAX_PDF_PAGES]:
            pages.append((page.extract_text() or "").strip())
        meta_title = ""
        if reader.metadata and reader.metadata.title:
            meta_title = str(reader.metadata.title)
        text = "\n\n".join(p for p in pages if p)
        return ParsedPage(text=re.sub(r"[ \t]+\n", "\n", text), title=meta_title)
    except Exception:
        return ParsedPage(text="")


def _title(soup: BeautifulSoup) -> str:
    og = soup.find("meta", attrs={"property": "og:title"})
    if isinstance(og, Tag) and og.get("content"):
        return str(og["content"]).strip()
    if soup.title and soup.title.string:
        return soup.title.string.strip()
    h1 = soup.find("h1")
    return h1.get_text(" ", strip=True) if isinstance(h1, Tag) else ""


_DATE_KEYS: tuple[tuple[str, dict[str, Any]], ...] = (
    ("meta", {"property": "article:published_time"}),
    ("meta", {"name": "date"}),
    ("meta", {"name": "pubdate"}),
    ("meta", {"itemprop": "datePublished"}),
    ("meta", {"property": "og:updated_time"}),
)


def _published(soup: BeautifulSoup) -> str | None:
    for name, attrs in _DATE_KEYS:
        el = soup.find(name, attrs=attrs)
        if isinstance(el, Tag) and el.get("content"):
            return str(el["content"]).strip()[:40]
    for script in soup.find_all("script", attrs={"type": "application/ld+json"}):
        try:
            data = json.loads(script.string or "")
        except (ValueError, TypeError):
            continue
        items = data if isinstance(data, list) else [data]
        for item in items:
            if isinstance(item, dict) and item.get("datePublished"):
                return str(item["datePublished"])[:40]
    t = soup.find("time", attrs={"datetime": True})
    if isinstance(t, Tag):
        return str(t["datetime"])[:40]
    return None


def _to_markdown(html: str) -> str:
    soup = BeautifulSoup(html, "lxml")
    for tag in soup(_BOILERPLATE):
        tag.decompose()
    root = soup.find("article") or soup.find("main") or soup.body or soup
    lines: list[str] = []
    for el in root.find_all(_BLOCKS):
        if not isinstance(el, Tag):
            continue
        # Skip containers whose text is emitted by a nested block (e.g. li > p).
        if el.name in {"li", "blockquote"} and el.find(["p", "li"]):
            continue
        if el.name == "tr":
            cells = [c.get_text(" ", strip=True) for c in el.find_all(["td", "th"])]
            if any(cells):
                lines.append("| " + " | ".join(cells) + " |")
            continue
        text = el.get_text(" ", strip=True)
        if not text:
            continue
        if el.name.startswith("h") and len(el.name) == 2 and el.name[1].isdigit():
            lines.append("#" * int(el.name[1]) + " " + text)
        elif el.name == "li":
            lines.append(f"- {text}")
        elif el.name == "pre":
            lines.append("```\n" + el.get_text("\n", strip=False).strip("\n") + "\n```")
        elif el.name == "blockquote":
            lines.append("> " + text)
        else:
            lines.append(text)
    if not lines:
        raw = root.get_text("\n", strip=True)
        return re.sub(r"\n{3,}", "\n\n", raw)
    return "\n\n".join(lines)
