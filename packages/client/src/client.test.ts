// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 Ved Buddaraju

import { describe, expect, it } from "vitest";
import { createClient, GleanWiseError } from "./client";
import { parseSse } from "./sse";
import { initialState, reduce, startState } from "./state";
import type { GleanWiseEvent } from "./types";

const enc = new TextEncoder();
function streamOf(chunks: (string | Uint8Array)[]): ReadableStream<Uint8Array> {
  return new ReadableStream({
    start(c) {
      for (const ch of chunks) c.enqueue(typeof ch === "string" ? enc.encode(ch) : ch);
      c.close();
    },
  });
}
async function collect(s: ReadableStream<Uint8Array>) {
  const out = [];
  for await (const m of parseSse(s)) out.push(m);
  return out;
}

describe("parseSse", () => {
  it("parses ids, events and multi-line data", async () => {
    const out = await collect(
      streamOf(['id: 1\nevent: plan\ndata: {"a":1}\n\nid: 2\nevent: x\ndata: l1\ndata: l2\n\n']),
    );
    expect(out).toEqual([
      { id: "1", event: "plan", data: '{"a":1}', retry: undefined },
      { id: "2", event: "x", data: "l1\nl2", retry: undefined },
    ]);
  });

  it("handles CRLF, CR, comments/pings and a BOM", async () => {
    const out = await collect(
      streamOf(["\uFEFF: ping\r\n\r\nid: 5\r\nevent: a\r\ndata: 1\r\n\r\n", "event: b\rdata: 2\r\r"]),
    );
    expect(out.map((m) => [m.id, m.event, m.data])).toEqual([
      ["5", "a", "1"],
      ["5", "b", "2"],
    ]);
  });

  it("survives chunk boundaries anywhere, including inside multi-byte characters and CRLF", async () => {
    const bytes = enc.encode("id: 9\r\nevent: e\r\ndata: héllo 🐱\r\n\r\n");
    const chunks = Array.from(bytes, (b) => new Uint8Array([b])); // one byte at a time
    const out = await collect(streamOf(chunks));
    expect(out).toHaveLength(1);
    expect(out[0].data).toBe("héllo 🐱");
  });

  it("drops an unterminated trailing block", async () => {
    const out = await collect(streamOf(["event: a\ndata: 1\n\nevent: b\ndata: partial"]));
    expect(out.map((m) => m.event)).toEqual(["a"]);
  });
});

const frame = (id: number, event: string, data: unknown) =>
  `id: ${id}\nevent: ${event}\ndata: ${JSON.stringify(data)}\n\n`;
const done = {
  query_id: "q",
  thread_id: "t",
  status: "complete",
  answer: "Hi [1]",
  citations: [],
  sources: [],
  follow_ups: [],
  usage: {},
  duration_ms: 5,
};

function fakeFetch(handler: (url: string, init: RequestInit) => Response | Promise<Response>): typeof fetch {
  return ((url: string, init: RequestInit) => Promise.resolve(handler(url, init))) as typeof fetch;
}

describe("GleanWiseClient streaming", () => {
  it("resumes with Last-Event-ID after a dropped connection and skips replayed events", async () => {
    const seen: (string | null)[] = [];
    let calls = 0;
    const f = fakeFetch((url, init) => {
      if (url.endsWith("/query"))
        return new Response(JSON.stringify({ query_id: "q", thread_id: "t", stream_url: "/stream/q" }), {
          status: 202,
          headers: { "content-type": "application/json" },
        });
      calls++;
      seen.push(new Headers(init.headers).get("Last-Event-ID"));
      if (calls === 1)
        return new Response(
          streamOf([
            frame(1, "plan", { steps: [], mode: "quick", subqueries: [] }),
            frame(2, "answer_delta", { text: "Hel" }),
          ]),
        );
      // server replays from id 2 (overlap) then finishes
      return new Response(
        streamOf([
          frame(2, "answer_delta", { text: "Hel" }),
          frame(3, "answer_delta", { text: "lo" }),
          frame(4, "done", done),
        ]),
      );
    });
    const c = createClient({ baseUrl: "http://x", fetch: f });
    const h = await c.query({ query: "hi" });
    const events: GleanWiseEvent[] = [];
    for await (const ev of h.events()) events.push(ev);
    expect(seen).toEqual([null, "2"]);
    expect(events.map((e) => e.id)).toEqual([1, 2, 3, 4]); // no duplicate id 2
  });

  it("does not retry on 404 and surfaces the server's error envelope", async () => {
    let calls = 0;
    const f = fakeFetch(() => {
      calls++;
      return new Response(JSON.stringify({ error: { code: "not_found", message: "expired", hint: "ask again" } }), {
        status: 404,
        headers: { "content-type": "application/json" },
      });
    });
    const c = createClient({ baseUrl: "http://x", fetch: f });
    await expect(async () => {
      for await (const _ of c.streamEvents("q")) void _;
    }).rejects.toMatchObject({ code: "not_found", hint: "ask again", status: 404 });
    expect(calls).toBe(1);
  });

  it("result() throws GleanWiseError with actionable fields when the stream ends in an error event", async () => {
    const f = fakeFetch((url) =>
      url.endsWith("/query")
        ? new Response(JSON.stringify({ query_id: "q", thread_id: "t", stream_url: "" }), {
            status: 202,
            headers: { "content-type": "application/json" },
          })
        : new Response(
            streamOf([
              frame(1, "error", {
                code: "llm_auth",
                message: "bad key",
                hint: "fix it",
                action: "open_settings",
                retryable: false,
              }),
            ]),
          ),
    );
    const h = await createClient({ baseUrl: "http://x", fetch: f }).query({ query: "hi" });
    const err = await h.result().catch((e) => e);
    expect(err).toBeInstanceOf(GleanWiseError);
    expect(err).toMatchObject({ code: "llm_auth", action: "open_settings", hint: "fix it" });
  });

  it("sends the bearer token on every request", async () => {
    const auth: (string | null)[] = [];
    const f = fakeFetch((_u, init) => {
      auth.push(new Headers(init.headers).get("Authorization"));
      return new Response("[]", { headers: { "content-type": "application/json" } });
    });
    await createClient({ baseUrl: "http://x", token: () => "tok", fetch: f }).listThreads();
    expect(auth).toEqual(["Bearer tok"]);
  });

  it("network failures become an actionable GleanWiseError", async () => {
    const f = (() => Promise.reject(new TypeError("fetch failed"))) as typeof fetch;
    await expect(createClient({ baseUrl: "http://x", fetch: f }).listThreads()).rejects.toMatchObject({
      code: "network",
      action: "open_diagnostics",
    });
  });
});

describe("reducer", () => {
  const ev = <T extends GleanWiseEvent["event"]>(
    event: T,
    data: Extract<GleanWiseEvent, { event: T }>["data"],
  ): GleanWiseEvent => ({ id: 1, event, data }) as GleanWiseEvent;

  it("tracks phases, sources, drafts and the upgrade", () => {
    let s = startState("q", "t");
    s = reduce(s, ev("plan", { steps: ["a"], mode: "quick", rewritten_query: null, subqueries: [] }));
    expect(s.phase).toBe("searching");
    s = reduce(
      s,
      ev("sources", {
        sources: [
          {
            id: 1,
            url: "https://a",
            title: "A",
            snippet: "",
            domain: "a",
            engines: [],
            used_in_answer: false,
            state: "found",
          },
        ],
      }),
    );
    expect(s.phase).toBe("reading");
    s = reduce(s, ev("source_update", { id: 1, state: "read", reason: null }));
    s = reduce(s, ev("answer_delta", { text: "Draft", draft: true }));
    expect(s).toMatchObject({ phase: "writing", draft: true, answer: "Draft" });
    s = reduce(s, ev("answer_upgrade", { reason: "full_pages" }));
    expect(s).toMatchObject({ answer: "", refining: true, draft: false });
    s = reduce(s, ev("answer_delta", { text: "Final [1]", draft: false }));
    s = reduce(
      s,
      ev("answer_complete", {
        text: "Final [1]",
        citations: [{ number: 1, url: "https://a", title: "A", excerpt: "", source_id: 1 }],
      }),
    );
    expect(s.refining).toBe(false);
    expect(s.sources[0].used_in_answer).toBe(true);
  });

  it("sources are idempotent by id (Deep rounds re-announce)", () => {
    const src = {
      id: 1,
      url: "https://a",
      title: "A",
      snippet: "",
      domain: "a",
      engines: [],
      used_in_answer: false,
      state: "found" as const,
    };
    let s = reduce(initialState, ev("sources", { sources: [src] }));
    s = reduce(s, ev("sources", { sources: [src, { ...src, id: 2, url: "https://b" }] }));
    expect(s.sources.map((x) => x.id)).toEqual([1, 2]);
  });

  it("cancel keeps the partial answer; error clears transient flags", () => {
    let s = reduce(startState(), ev("answer_delta", { text: "part", draft: false }));
    s = reduce(s, ev("done", { ...done, status: "cancelled", answer: "" } as never));
    expect(s).toMatchObject({ phase: "cancelled", answer: "part" });
    const e = reduce(startState(), ev("error", { code: "x", message: "m", retryable: false }));
    expect(e.phase).toBe("error");
  });
});
