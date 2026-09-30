// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 Ved Buddaraju

import type { AnswerState, SourceView, ThreadSummary } from "@gleanwise/react";

export type Group = "pinned" | "today" | "yesterday" | "week" | "earlier";

export function groupThreads(threads: ThreadSummary[], now = new Date()): { group: Group; items: ThreadSummary[] }[] {
  const startOfDay = new Date(now.getFullYear(), now.getMonth(), now.getDate()).getTime();
  const buckets = new Map<Group, ThreadSummary[]>();
  for (const t of threads) {
    const at = Date.parse(t.updated_at);
    const g: Group = t.pinned
      ? "pinned"
      : at >= startOfDay
        ? "today"
        : at >= startOfDay - 86_400_000
          ? "yesterday"
          : at >= startOfDay - 6 * 86_400_000
            ? "week"
            : "earlier";
    buckets.set(g, [...(buckets.get(g) ?? []), t]);
  }
  return (["pinned", "today", "yesterday", "week", "earlier"] as Group[])
    .filter((g) => buckets.has(g))
    .map((g) => ({ group: g, items: buckets.get(g)! }));
}

/** The answer plus a numbered source list, as portable Markdown. */
export function answerToMarkdown(
  query: string,
  s: Pick<AnswerState, "answer" | "citations" | "sources">,
  labels: { sources: string },
): string {
  const cited = s.citations.length
    ? s.citations.map((c) => ({ n: c.number, title: c.title, url: c.url }))
    : s.sources.filter((x) => x.used_in_answer).map((x) => ({ n: x.id, title: x.title, url: x.url }));
  const lines = [`# ${query}`, "", s.answer.trim()];
  if (cited.length)
    lines.push("", `**${labels.sources}**`, "", ...cited.map((c) => `${c.n}. [${c.title || c.url}](${c.url})`));
  return lines.join("\n") + "\n";
}

export function researchLogToMarkdown(query: string, s: AnswerState): string {
  const lines = [`# Research log: ${query}`, ""];
  if (s.researchSummary) lines.push(`_${s.researchSummary}_`, "");
  if (s.plan?.subqueries.length) lines.push("## Planned searches", "", ...s.plan.subqueries.map((q) => `- ${q}`), "");
  if (s.reasoning.trim()) lines.push("## Reasoning", "", s.reasoning.trim(), "");
  if (s.visits.length) {
    lines.push("## Sites visited", "");
    let round: number | null | undefined;
    for (const v of s.visits) {
      if (v.round !== round) {
        round = v.round;
        lines.push(`### Round ${round ?? "-"}`);
      }
      lines.push(`- [${v.title || v.url}](${v.url})`);
    }
    lines.push("");
  }
  return lines.join("\n");
}

export function download(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob);
  const a = Object.assign(document.createElement("a"), { href: url, download: filename });
  document.body.append(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 10_000);
}

export const slug = (s: string) =>
  s
    .toLowerCase()
    .replace(/[^\p{L}\p{N}]+/gu, "-")
    .replace(/^-|-$/g, "")
    .slice(0, 48) || "gleanwise-thread";

export function faviconOf(s: SourceView, resolve: (p: string) => string | undefined) {
  return s.favicon ? resolve(s.favicon) : undefined;
}
