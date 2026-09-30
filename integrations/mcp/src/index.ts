#!/usr/bin/env node
// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 Ved Buddaraju

/**
 * MCP server exposing GleanWise to agents: search, answer, fetch_page, retrieve.
 * `search` is a fast ranked search (no LLM, no full pipeline); `answer` runs the full cited pipeline.
 */
import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import { z } from "zod";
import { createClient, GleanWiseError } from "@gleanwise/client";

const client = createClient({
  baseUrl: process.env.GLEANWISE_API_URL || "http://127.0.0.1:8787",
  token: process.env.GLEANWISE_API_TOKEN,
});

const server = new McpServer({ name: "gleanwise", version: "0.2.0" });
const focus = z.enum(["general", "academic", "news", "social"]).default("general");

type ToolResult = { content: { type: "text"; text: string }[]; isError?: boolean };
const ok = (v: unknown): ToolResult => ({
  content: [{ type: "text", text: typeof v === "string" ? v : JSON.stringify(v, null, 2) }],
});
const fail = (e: unknown): ToolResult => {
  const msg =
    e instanceof GleanWiseError
      ? `${e.message}${e.hint ? ` — ${e.hint}` : ""}`
      : e instanceof Error
        ? e.message
        : String(e);
  return { isError: true, content: [{ type: "text", text: msg }] };
};
const guard =
  <A>(fn: (a: A) => Promise<ToolResult>) =>
  async (a: A): Promise<ToolResult> => {
    try {
      return await fn(a);
    } catch (e) {
      return fail(e);
    }
  };

server.registerTool(
  "search",
  {
    title: "Web search",
    description:
      "Ranked web results (title, url, snippet). Fast; no answer is written. Use `answer` when you need a synthesized, cited response.",
    inputSchema: { query: z.string().min(1), focus, limit: z.number().int().min(1).max(20).default(8) },
  },
  guard(async ({ query, focus, limit }) => ok(await client.search(query, { focus, limit }))),
);

server.registerTool(
  "answer",
  {
    title: "Cited answer",
    description:
      "Researches the web and returns a cited answer. `quick` ~seconds, `pro` plans several searches, `deep` runs multiple research rounds (slow).",
    inputSchema: { query: z.string().min(1), mode: z.enum(["quick", "pro", "deep"]).default("quick"), focus },
  },
  guard(async ({ query, mode, focus }) => {
    const handle = await client.query({ query, mode, focus, persist: false });
    const done = await handle.result();
    return ok({
      answer: done.answer,
      citations: done.citations,
      sources: done.sources.map((s) => ({ id: s.id, title: s.title, url: s.url })),
      follow_ups: done.follow_ups,
    });
  }),
);

server.registerTool(
  "fetch_page",
  {
    title: "Fetch a page",
    description: "Fetch a public URL and return its cleaned text (SSRF-guarded, robots-aware).",
    inputSchema: { url: z.string().url(), max_chars: z.number().int().min(500).max(100000).default(20000) },
  },
  guard(async ({ url, max_chars }) => ok(await client.fetchPage(url, max_chars))),
);

server.registerTool(
  "retrieve",
  {
    title: "Search the local index",
    description: "Semantic + keyword search over pages GleanWise has already read. Returns passages with URLs.",
    inputSchema: { query: z.string().min(1), limit: z.number().int().min(1).max(30).default(8) },
  },
  guard(async ({ query, limit }) => ok(await client.retrieve(query, { limit }))),
);

await server.connect(new StdioServerTransport());
