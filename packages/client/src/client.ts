// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 Ved Buddaraju

import { parseSse } from "./sse";
import { initialState, reduce, startState, type AnswerState } from "./state";
import {
  TERMINAL_EVENTS,
  type DoneEvent,
  type EgressActivity,
  type ErrorBody,
  type EventName,
  type FetchResponse,
  type HealthResponse,
  type MessageOut,
  type GleanWiseEvent,
  type QueryAccepted,
  type QueryInput,
  type QueryRequest,
  type QueryStatus,
  type RetrieveResponse,
  type SearchResponse,
  type SettingsUpdate,
  type SettingsView,
  type SetupTestResult,
  type ThreadDetail,
  type ThreadSummary,
} from "./types";

export interface ClientOptions {
  /** API origin. Defaults to same-origin in browsers, http://127.0.0.1:8787 elsewhere. */
  baseUrl?: string;
  /** Bearer token (or a function returning one) for servers started with GLEANWISE_API_TOKEN. */
  token?: string | (() => string | undefined);
  fetch?: typeof fetch;
  headers?: Record<string, string>;
  /** Max reconnect attempts per stream without progress. Default 5. */
  maxReconnects?: number;
}

/** Error with the server's actionable fields. `action` tells UIs which button to show. */
export class GleanWiseError extends Error {
  readonly code: string;
  readonly hint?: string | null;
  readonly action?: string | null;
  readonly retryable: boolean;
  readonly status?: number;
  constructor(body: Partial<ErrorBody> & { message: string }, status?: number) {
    super(body.message);
    this.name = "GleanWiseError";
    this.code = body.code ?? "error";
    this.hint = body.hint;
    this.action = body.action;
    this.retryable = body.retryable ?? false;
    this.status = status;
  }
  toBody(): ErrorBody {
    return {
      code: this.code,
      message: this.message,
      hint: this.hint ?? null,
      action: this.action ?? null,
      retryable: this.retryable,
    };
  }
}

const defaultBase = () =>
  typeof location !== "undefined" && location.protocol.startsWith("http") ? "" : "http://127.0.0.1:8787";
const sleep = (ms: number, signal?: AbortSignal) =>
  new Promise<void>((resolve, reject) => {
    const t = setTimeout(resolve, ms);
    signal?.addEventListener("abort", () => (clearTimeout(t), reject(new DOMException("Aborted", "AbortError"))), {
      once: true,
    });
  });

export class QueryHandle {
  constructor(
    private readonly client: GleanWiseClient,
    readonly queryId: string,
    readonly threadId: string,
    private readonly signal?: AbortSignal,
  ) {}

  /** Events in order. Reconnects transparently (with Last-Event-ID) if the connection drops. */
  events(): AsyncGenerator<GleanWiseEvent> {
    return this.client.streamEvents(this.queryId, { signal: this.signal });
  }

  /** Resolves with the final event payload; rejects with a GleanWiseError if the query failed. */
  async result(): Promise<DoneEvent> {
    for await (const ev of this.events()) {
      if (ev.event === "done") return ev.data;
      if (ev.event === "error") throw new GleanWiseError(ev.data);
    }
    throw new GleanWiseError({
      code: "stream_ended",
      message: "The stream ended before an answer arrived.",
      retryable: true,
    });
  }

  cancel(): Promise<void> {
    return this.client.cancel(this.queryId);
  }
}

export class GleanWiseClient {
  readonly baseUrl: string;
  private readonly opts: ClientOptions;
  constructor(opts: ClientOptions = {}) {
    this.opts = opts;
    this.baseUrl = (opts.baseUrl ?? defaultBase()).replace(/\/+$/, "");
  }

  private get fetchImpl(): typeof fetch {
    return this.opts.fetch ?? globalThis.fetch.bind(globalThis);
  }

  headers(extra?: Record<string, string>): Record<string, string> {
    const t = typeof this.opts.token === "function" ? this.opts.token() : this.opts.token;
    return { ...(t ? { Authorization: `Bearer ${t}` } : {}), ...this.opts.headers, ...extra };
  }

  url(path: string): string {
    return path.startsWith("http") ? path : `${this.baseUrl}${path}`;
  }

  /** Absolute URL for a server-relative asset (e.g. a favicon proxy path). */
  asset(path: string | null | undefined): string | undefined {
    return path ? this.url(path) : undefined;
  }

  /** Same-origin URL that loads a remote image through the server (no direct contact with the origin). */
  imageUrl(remote: string): string {
    return this.url(`/proxy/image?url=${encodeURIComponent(remote)}`);
  }

  async request<T>(method: string, path: string, body?: unknown, signal?: AbortSignal): Promise<T> {
    let res: Response;
    try {
      res = await this.fetchImpl(this.url(path), {
        method,
        signal,
        headers: this.headers(body !== undefined ? { "Content-Type": "application/json" } : undefined),
        body: body !== undefined ? JSON.stringify(body) : undefined,
      });
    } catch (e) {
      if ((e as Error)?.name === "AbortError") throw e;
      throw new GleanWiseError({
        code: "network",
        message: "Can't reach the GleanWise server.",
        hint: `Is it running at ${this.baseUrl || "this address"}?`,
        action: "open_diagnostics",
        retryable: true,
      });
    }
    if (!res.ok) throw await this.errorFrom(res);
    if (res.status === 204) return undefined as T;
    const ctype = res.headers.get("content-type") ?? "";
    return (ctype.includes("json") ? await res.json() : await res.text()) as T;
  }

  private async errorFrom(res: Response): Promise<GleanWiseError> {
    try {
      const j = (await res.json()) as { error?: Partial<ErrorBody> };
      if (j.error?.message) return new GleanWiseError({ ...j.error, message: j.error.message }, res.status);
    } catch {
      /* not JSON */
    }
    return new GleanWiseError(
      {
        code: `http_${res.status}`,
        message: `The server replied ${res.status} ${res.statusText}`.trim(),
        retryable: res.status >= 500,
      },
      res.status,
    );
  }

  // --- queries -------------------------------------------------------------------------------
  async query(req: QueryInput, opts?: { signal?: AbortSignal }): Promise<QueryHandle> {
    const acc = await this.request<QueryAccepted>("POST", "/query", req, opts?.signal);
    return new QueryHandle(this, acc.query_id, acc.thread_id, opts?.signal);
  }

  /** Convenience: run a query and get incremental UI state after every event. */
  async ask(req: QueryInput, onState: (s: AnswerState) => void, opts?: { signal?: AbortSignal }): Promise<AnswerState> {
    const handle = await this.query(req, opts);
    let state = startState(handle.queryId, handle.threadId);
    onState(state);
    for await (const ev of handle.events()) {
      state = reduce(state, ev);
      onState(state);
    }
    return state;
  }

  cancel(queryId: string): Promise<void> {
    return this.request("POST", `/queries/${encodeURIComponent(queryId)}/cancel`).then(() => undefined);
  }

  status(queryId: string): Promise<QueryStatus> {
    return this.request("GET", `/queries/${encodeURIComponent(queryId)}`);
  }

  async *streamEvents(
    queryId: string,
    o: { after?: number; signal?: AbortSignal } = {},
  ): AsyncGenerator<GleanWiseEvent> {
    let last = o.after ?? 0;
    let failures = 0;
    const max = this.opts.maxReconnects ?? 5;
    for (;;) {
      let progressed = false;
      try {
        const res = await this.fetchImpl(this.url(`/stream/${encodeURIComponent(queryId)}`), {
          signal: o.signal,
          headers: this.headers({ Accept: "text/event-stream", ...(last ? { "Last-Event-ID": String(last) } : {}) }),
        });
        if (!res.ok || !res.body) throw await this.errorFrom(res);
        for await (const msg of parseSse(res.body)) {
          const id = Number(msg.id ?? 0);
          if (id && id <= last) continue; // replay overlap
          if (id) last = id;
          let data: unknown;
          try {
            data = JSON.parse(msg.data);
          } catch {
            continue;
          }
          progressed = true;
          const ev = { id, event: msg.event as EventName, data } as GleanWiseEvent;
          yield ev;
          if (TERMINAL_EVENTS.includes(ev.event)) return;
        }
      } catch (e) {
        if ((e as Error)?.name === "AbortError") throw e;
        if (e instanceof GleanWiseError && e.status && e.status < 500 && e.status !== 429) throw e; // 404/401: retrying can't help
      }
      failures = progressed ? 0 : failures + 1;
      if (failures > max) {
        throw new GleanWiseError({
          code: "stream_lost",
          message: "Lost the connection to the server.",
          hint: "Check that it is still running, then retry.",
          action: "retry",
          retryable: true,
        });
      }
      await sleep(Math.min(4000, 250 * 2 ** failures), o.signal);
    }
  }

  // --- threads ---------------------------------------------------------------------------------
  listThreads(params: { q?: string; limit?: number; offset?: number } = {}): Promise<ThreadSummary[]> {
    const qs = new URLSearchParams(
      Object.entries(params)
        .filter(([, v]) => v !== undefined)
        .map(([k, v]) => [k, String(v)]),
    );
    return this.request("GET", `/threads${qs.size ? `?${qs}` : ""}`);
  }
  getThread(id: string): Promise<ThreadDetail> {
    return this.request("GET", `/threads/${encodeURIComponent(id)}`);
  }
  updateThread(id: string, patch: { title?: string; pinned?: boolean }): Promise<void> {
    return this.request("PATCH", `/threads/${encodeURIComponent(id)}`, patch).then(() => undefined);
  }
  deleteThread(id: string): Promise<void> {
    return this.request("DELETE", `/threads/${encodeURIComponent(id)}`).then(() => undefined);
  }
  deleteMessage(threadId: string, messageId: string): Promise<void> {
    return this.request(
      "DELETE",
      `/threads/${encodeURIComponent(threadId)}/messages/${encodeURIComponent(messageId)}`,
    ).then(() => undefined);
  }
  /** Download a conversation. Returns a Blob so browsers can save it and Node can write it. */
  async exportThread(id: string, format: "md" | "pdf"): Promise<Blob> {
    const res = await this.fetchImpl(this.url(`/threads/${encodeURIComponent(id)}/export?format=${format}`), {
      headers: this.headers(),
    });
    if (!res.ok) throw await this.errorFrom(res);
    return res.blob();
  }

  // --- settings, health, tools -----------------------------------------------------------------
  getSettings(): Promise<SettingsView> {
    return this.request("GET", "/settings");
  }
  updateSettings(patch: SettingsUpdate): Promise<SettingsView> {
    return this.request("PUT", "/settings", patch);
  }
  testSetup(
    trial: { llm_model?: string; llm_api_key?: string; llm_api_base?: string; searxng_url?: string } = {},
  ): Promise<SetupTestResult> {
    return this.request("POST", "/setup/test", trial);
  }
  diagnostics(): Promise<HealthResponse> {
    return this.request("GET", "/diagnostics");
  }
  /** Readiness (200 when usable, 503 when a component is down) — both carry the same report. */
  async ready(): Promise<HealthResponse> {
    let res: Response;
    try {
      res = await this.fetchImpl(this.url("/readyz"), { headers: this.headers() });
    } catch {
      throw new GleanWiseError({
        code: "network",
        message: "Can't reach the GleanWise server.",
        hint: `Is it running at ${this.baseUrl || "this address"}?`,
        action: "open_diagnostics",
        retryable: true,
      });
    }
    if (res.status === 200 || res.status === 503) return (await res.json()) as HealthResponse;
    throw await this.errorFrom(res);
  }
  clearCache(): Promise<void> {
    return this.request("POST", "/data/clear-cache").then(() => undefined);
  }
  egressActivity(): Promise<EgressActivity> {
    return this.request("GET", "/privacy/egress");
  }
  clearEgress(): Promise<void> {
    return this.request("POST", "/privacy/egress/clear").then(() => undefined);
  }
  wipeData(): Promise<void> {
    return this.request("POST", "/data/wipe").then(() => undefined);
  }
  feedback(queryId: string, thumb: -1 | 0 | 1, comment?: string): Promise<void> {
    return this.request("POST", "/feedback", { query_id: queryId, thumb, comment }).then(() => undefined);
  }
  search(query: string, o: { focus?: QueryRequest["focus"]; limit?: number } = {}): Promise<SearchResponse> {
    return this.request("POST", "/search", { query, ...o });
  }
  fetchPage(url: string, maxChars = 20000): Promise<FetchResponse> {
    return this.request("POST", "/fetch", { url, max_chars: maxChars });
  }
  retrieve(query: string, o: { urls?: string[]; limit?: number } = {}): Promise<RetrieveResponse> {
    return this.request("POST", "/retrieve", { query, ...o });
  }
}

export function createClient(opts?: ClientOptions | string): GleanWiseClient {
  return new GleanWiseClient(typeof opts === "string" ? { baseUrl: opts } : opts);
}

export type { AnswerState, MessageOut };
export { initialState, reduce, startState };
