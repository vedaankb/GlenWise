// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 Ved Buddaraju

// @vitest-environment happy-dom
import { describe, expect, it } from "vitest";
import { renderAnswer, safeHref } from "./index";

const html = (n: DocumentFragment) => {
  const d = document.createElement("div");
  d.append(n);
  return d;
};

describe("widget safety", () => {
  it("only allows http(s) links", () => {
    expect(safeHref("https://a.example/x")).toBe("https://a.example/x");
    expect(safeHref("javascript:alert(1)")).toBeNull();
    expect(safeHref("data:text/html,<script>1</script>")).toBeNull();
    expect(safeHref("not a url")).toBeNull();
  });

  it("never turns answer text into markup", () => {
    const d = html(
      renderAnswer("<img src=x onerror=alert(1)> **bold** `<b>` [1] [9]", (n) =>
        n === 1 ? "https://a.example" : null,
      ),
    );
    expect(d.querySelector("img")).toBeNull();
    expect(d.querySelector("script")).toBeNull();
    expect(d.textContent).toContain("<img src=x onerror=alert(1)>");
    expect(d.querySelector("strong")?.textContent).toBe("bold");
    expect(d.querySelector("code")?.textContent).toBe("<b>");
    const cites = d.querySelectorAll("a.cite");
    expect(cites).toHaveLength(1); // [9] has no source, so it stays plain text
    expect(cites[0].getAttribute("rel")).toContain("noopener");
  });

  it("renders paragraphs and lists", () => {
    const d = html(renderAnswer("# Title\n\nOne.\n\n- a\n- b", () => null));
    expect(d.querySelectorAll("p")).toHaveLength(2);
    expect(d.querySelectorAll("li")).toHaveLength(2);
  });
});
