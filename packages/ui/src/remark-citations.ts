// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 Ved Buddaraju

import { visit } from "unist-util-visit";

interface TextNode {
  type: "text";
  value: string;
}
interface Parent {
  children: unknown[];
  type: string;
}

/** Turns `[3]` into a citation node, but only for numbers that match a known source. */
export function remarkCitations(known: ReadonlySet<number>) {
  return () => (tree: unknown) => {
    visit(tree as never, "text", (node: TextNode, index: number | undefined, parent: Parent | undefined) => {
      if (!parent || index === undefined || parent.type === "link" || parent.type === "linkReference") return;
      const re = /\[(\d{1,3})\]/g;
      const out: unknown[] = [];
      let last = 0;
      for (const m of node.value.matchAll(re)) {
        const n = Number(m[1]);
        if (!known.has(n)) continue;
        if (m.index > last) out.push({ type: "text", value: node.value.slice(last, m.index) });
        out.push({ type: "citation", data: { hName: "gw-cite", hProperties: { n: String(n) } }, children: [] });
        last = m.index + m[0].length;
      }
      if (!out.length) return;
      if (last < node.value.length) out.push({ type: "text", value: node.value.slice(last) });
      parent.children.splice(index, 1, ...out);
      return index + out.length;
    });
  };
}
