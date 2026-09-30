# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Ved Buddaraju

"""Conversation export: Markdown (with footnoted sources) and a clean PDF."""

from __future__ import annotations

import io
import re
from xml.sax.saxutils import escape

from gleanwise.models import ThreadDetail


def safe_filename(title: str) -> str:
    name = re.sub(r"[^\w\- ]+", "", title, flags=re.UNICODE).strip().replace(" ", "-")
    return (name or "conversation")[:60]


def export_markdown(t: ThreadDetail) -> str:
    out = [f"# {t.title}", ""]
    for m in t.messages:
        if m.role == "user":
            out += [f"## {m.content}", ""]
            continue
        out += [m.content, ""]
        if m.citations:
            out.append("**Sources**")
            out.append("")
            for c in m.citations:
                out.append(f"{c.number}. [{c.title or c.url}]({c.url})")
            out.append("")
    return "\n".join(out).strip() + "\n"


def _para_markup(text: str) -> str:
    """Tiny Markdown → ReportLab inline markup (bold, italics, code, citation markers)."""
    s = escape(text)
    s = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", s)
    s = re.sub(r"(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)", r"<i>\1</i>", s)
    s = re.sub(r"`([^`]+)`", r'<font face="Courier">\1</font>', s)
    s = re.sub(r"\[(\d{1,3})\]", r'<super><font size="7" color="#4f46e5">\1</font></super>', s)
    return s


def export_pdf(t: ThreadDetail) -> bytes:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer

    styles = getSampleStyleSheet()
    body = ParagraphStyle(
        "body", parent=styles["BodyText"], fontSize=10.5, leading=15, spaceAfter=6
    )
    h1 = ParagraphStyle(
        "h1", parent=styles["Title"], fontSize=20, leading=24, alignment=0, spaceAfter=10
    )
    q = ParagraphStyle(
        "q", parent=styles["Heading2"], fontSize=13, leading=17, spaceBefore=14, spaceAfter=6
    )
    h3 = ParagraphStyle("h3", parent=styles["Heading3"], fontSize=11.5, leading=15, spaceBefore=8)
    small = ParagraphStyle(
        "small", parent=body, fontSize=8.5, leading=11, textColor=colors.HexColor("#555555")
    )
    bullet = ParagraphStyle("bullet", parent=body, leftIndent=14, bulletIndent=4)

    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=A4,
        leftMargin=20 * mm,
        rightMargin=20 * mm,
        topMargin=18 * mm,
        bottomMargin=18 * mm,
        title=t.title,
        author="GleanWise",
    )
    flow: list = [Paragraph(escape(t.title), h1)]
    for m in t.messages:
        if m.role == "user":
            flow.append(Paragraph(escape(m.content), q))
            continue
        for block in re.split(r"\n{2,}", m.content.strip()):
            block = block.strip()
            if not block:
                continue
            if block.startswith("#"):
                flow.append(Paragraph(escape(block.lstrip("# ").strip()), h3))
            elif re.match(r"^[-*] ", block):
                for line in block.splitlines():
                    flow.append(
                        Paragraph(_para_markup(re.sub(r"^[-*] ", "", line)), bullet, bulletText="•")
                    )
            else:
                flow.append(Paragraph(_para_markup(block.replace("\n", " ")), body))
        if m.citations:
            flow.append(Spacer(1, 4))
            for c in m.citations:
                flow.append(
                    Paragraph(f"[{c.number}] {escape(c.title or c.url)} — {escape(c.url)}", small)
                )
    doc.build(flow)
    return buf.getvalue()
