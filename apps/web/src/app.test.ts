// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 Ved Buddaraju

import { describe, expect, it } from "vitest";
import type { ThreadSummary } from "@gleanwise/react";
import { ar } from "./i18n/ar";
import { en } from "./i18n/en";
import { resolveLocale, translate } from "./i18n";
import { groupThreads, answerToMarkdown } from "./lib/format";
import { parseRoute } from "./router";

describe("i18n", () => {
  it("has an Arabic string for every English key, with the same placeholders", () => {
    const missing = Object.keys(en).filter((k) => !(k in ar));
    expect(missing).toEqual([]);
    const slots = (s: string) => (s.match(/\{\w+\}/g) ?? []).sort().join(",");
    for (const [k, v] of Object.entries(en)) {
      expect(slots((ar as Record<string, string>)[k] ?? ""), k).toBe(slots(v));
    }
  });

  it("picks the locale from the stored preference, then the browser languages", () => {
    expect(resolveLocale("ar")).toBe("ar");
    expect(resolveLocale("auto", ["ar-EG", "en"])).toBe("ar");
    expect(resolveLocale("auto", ["fr-FR"])).toBe("en");
    expect(resolveLocale("xx", [])).toBe("en");
  });

  it("chooses plural forms and fills placeholders", () => {
    expect(translate("en", "answer.sources")).toBeTruthy();
    expect(translate("en", "cite.source", { n: 3 })).toContain("3");
  });
});

describe("router", () => {
  it("parses known routes and rejects unsafe thread ids", () => {
    expect(parseRoute("/")).toEqual({ name: "home", q: null });
    expect(parseRoute("/", "?q=hello%20world")).toEqual({ name: "home", q: "hello world" });
    expect(parseRoute("/c/abc-123")).toEqual({ name: "thread", id: "abc-123" });
    expect(parseRoute("/c/../etc/passwd").name).toBe("notfound");
    expect(parseRoute("/settings/")).toEqual({ name: "settings", section: null });
    expect(parseRoute("/nope").name).toBe("notfound");
  });
});

describe("thread grouping", () => {
  const mk = (id: string, updated_at: string, pinned = false) =>
    ({ id, title: id, pinned, updated_at }) as unknown as ThreadSummary;
  it("keeps pinned threads first and buckets the rest by recency", () => {
    const now = new Date("2026-05-10T15:00:00");
    const groups = groupThreads(
      [
        mk("old", "2026-01-01T10:00:00"),
        mk("pin", "2026-01-01T10:00:00", true),
        mk("now", "2026-05-10T09:00:00"),
        mk("yday", "2026-05-09T09:00:00"),
      ],
      now,
    );
    expect(groups.map((g) => g.group)).toEqual(["pinned", "today", "yesterday", "earlier"]);
  });
});

describe("export", () => {
  it("renders the answer with a numbered source list", () => {
    const md = answerToMarkdown(
      "Why?",
      {
        answer: "Because [1].",
        citations: [{ number: 1, title: "A", url: "https://a.example/" }] as never,
        sources: [],
      },
      { sources: "Sources" },
    );
    expect(md).toContain("# Why?");
    expect(md).toContain("1. [A](https://a.example/)");
  });
});
