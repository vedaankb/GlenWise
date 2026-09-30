// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 Ved Buddaraju

/** Split Markdown into top-level blocks (blank-line separated, fence-aware) so finished blocks can be memoised while streaming. */
export function splitBlocks(md: string): string[] {
  const blocks: string[] = [];
  let cur: string[] = [];
  let fence: string | null = null;
  for (const line of md.split("\n")) {
    const f = /^\s{0,3}(`{3,}|~{3,})/.exec(line);
    if (f) {
      if (!fence) fence = f[1][0];
      else if (f[1][0] === fence) fence = null;
    }
    if (!fence && line.trim() === "" && cur.length) {
      blocks.push(cur.join("\n"));
      cur = [];
    } else if (!(line.trim() === "" && !cur.length && !fence)) cur.push(line);
  }
  if (cur.length) blocks.push(cur.join("\n"));
  return blocks;
}

/**
 * LLMs write math as \( … \) and \[ … \]; remark-math wants $…$ / $$…$$. Currency such as "$5" is left
 * alone because single-dollar math is disabled in the renderer. Fenced and inline code are untouched.
 */
export function normalizeMath(md: string): string {
  const parts = md.split(/(```[\s\S]*?(?:```|$)|~~~[\s\S]*?(?:~~~|$)|`[^`\n]*`)/g);
  return parts
    .map((p, i) =>
      i % 2 === 1
        ? p
        : p
            .replace(/\\\[([\s\S]+?)\\\]/g, (_m, x: string) => `\n$$\n${x.trim()}\n$$\n`)
            .replace(/\\\(([\s\S]+?)\\\)/g, (_m, x: string) => `$$${x.trim()}$$`),
    )
    .join("");
}

export function textOf(node: unknown): string {
  if (typeof node === "string" || typeof node === "number") return String(node);
  if (Array.isArray(node)) return node.map(textOf).join("");
  if (node && typeof node === "object" && "props" in node)
    return textOf((node as { props: { children?: unknown } }).props.children);
  return "";
}

export function relativeTime(iso: string | null | undefined, locale?: string, now = Date.now()): string | null {
  if (!iso) return null;
  const t = Date.parse(iso);
  if (Number.isNaN(t)) return null;
  const days = Math.round((t - now) / 86_400_000);
  const rtf = new Intl.RelativeTimeFormat(locale, { numeric: "auto" });
  if (Math.abs(days) < 1) return rtf.format(0, "day");
  if (Math.abs(days) < 30) return rtf.format(days, "day");
  if (Math.abs(days) < 365) return rtf.format(Math.round(days / 30), "month");
  return rtf.format(Math.round(days / 365), "year");
}

export function safeUrl(raw: string): string | null {
  try {
    const u = new URL(raw);
    return u.protocol === "http:" || u.protocol === "https:" ? u.href : null;
  } catch {
    return null;
  }
}
