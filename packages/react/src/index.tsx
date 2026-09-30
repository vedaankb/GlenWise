// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 Ved Buddaraju

import {
  createContext,
  createElement,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";
import {
  GleanWiseClient,
  GleanWiseError,
  initialState,
  reduce,
  startState,
  type AnswerState,
  type ClientOptions,
  type ErrorBody,
  type MessageOut,
  type GleanWiseEvent,
  type QueryInput,
  type SourceView,
} from "@gleanwise/client";

export * from "@gleanwise/client";

const Ctx = createContext<GleanWiseClient | null>(null);

export interface GleanWiseProviderProps {
  client?: GleanWiseClient;
  options?: ClientOptions;
  children?: ReactNode;
}

/** Provides a client to hooks. Pass an existing `client`, or `options` to create one. */
export function GleanWiseProvider({ client, options, children }: GleanWiseProviderProps) {
  const value = useMemo(() => client ?? new GleanWiseClient(options), [client, options]);
  return createElement(Ctx.Provider, { value }, children);
}

export function useGleanWiseClient(): GleanWiseClient {
  const c = useContext(Ctx);
  if (!c) throw new Error("useGleanWiseClient must be used inside <GleanWiseProvider>");
  return c;
}

/** Rebuilds display state from a stored assistant message, so reloaded threads look like live ones. */
export function stateFromMessage(m: MessageOut): AnswerState {
  const cited = new Set((m.citations ?? []).map((c) => c.number));
  const log = m.research_log ?? [];
  return {
    ...initialState,
    phase: "done",
    queryId: m.query_id ?? "",
    threadId: m.thread_id,
    messageId: m.id,
    answer: m.content,
    citations: m.citations ?? [],
    followUps: m.follow_ups ?? [],
    researchSummary: m.research_summary ?? undefined,
    reasoning: log
      .map((r) => {
        const qs = Array.isArray(r.queries) ? (r.queries as string[]).join("; ") : "";
        const head = `Round ${String(r.round)}: searched ${qs}\nRead ${String(r.read)} of ${String(r.found)} new pages.`;
        return r.reasoning ? `${head}\nAssessment: ${String(r.reasoning)}` : head;
      })
      .join("\n"),
    visits: log.flatMap((r) => {
      const round = typeof r.round === "number" ? r.round : null;
      const visited = Array.isArray(r.visited) ? (r.visited as { id: number; url: string; title?: string }[]) : [];
      return visited.map((v) => ({ source_id: v.id, url: v.url, title: v.title ?? "", round }));
    }),
    sources: (m.sources ?? []).map((s): SourceView => ({
      ...s,
      state: s.state ?? "read",
      used_in_answer: cited.has(s.id) || s.used_in_answer,
    })),
  };
}

export interface UseAnswerOptions {
  /** Called as soon as the server accepts a query, before any events, so apps can remember it (e.g. to resume after a reload). */
  onAccepted?(q: { queryId: string; threadId: string }): void;
}

export interface UseAnswer {
  state: AnswerState;
  /** True from the moment a query is submitted until a terminal event arrives. */
  busy: boolean;
  ask(req: QueryInput): Promise<AnswerState>;
  /** Stream an existing query by id (resume after reload or navigation). */
  attach(queryId: string, threadId?: string): Promise<AnswerState>;
  /** Ask the server to stop; the partial answer stays on screen. */
  cancel(): Promise<void>;
  /** Show an already-finished answer (e.g. from thread history) without contacting the server. */
  show(state: AnswerState): void;
  reset(): void;
}

/**
 * State machine for one streamed answer. Events are batched to one render per animation frame,
 * so a fast token stream never outpaces the screen.
 */
export function useAnswer(options: UseAnswerOptions = {}): UseAnswer {
  const client = useGleanWiseClient();
  const [state, setState] = useState<AnswerState>(initialState);
  const live = useRef<AnswerState>(initialState);
  const frame = useRef<number | null>(null);
  const abort = useRef<AbortController | null>(null);
  const activeQuery = useRef<string | null>(null);
  const onAccepted = useRef<UseAnswerOptions["onAccepted"]>(undefined);

  const flush = useCallback(() => {
    frame.current = null;
    setState(live.current);
  }, []);
  const push = useCallback(
    (next: AnswerState, immediate = false) => {
      live.current = next;
      if (immediate) {
        if (frame.current != null) cancelAnimationFrame(frame.current);
        flush();
      } else if (frame.current == null) frame.current = requestAnimationFrame(flush);
    },
    [flush],
  );

  useEffect(
    () => () => {
      abort.current?.abort();
      if (frame.current != null) cancelAnimationFrame(frame.current);
    },
    [],
  );

  const run = useCallback(
    async (queryId: string, threadId: string | undefined, ctl: AbortController) => {
      const failWith = (body: ErrorBody) =>
        push({ ...live.current, phase: "error", error: body, refining: false, draft: false }, true);
      activeQuery.current = queryId;
      push(startState(queryId, threadId), true);
      try {
        for await (const ev of client.streamEvents(queryId, { signal: ctl.signal }) as AsyncIterable<GleanWiseEvent>) {
          const terminal = ev.event === "done" || ev.event === "error";
          push(reduce(live.current, ev), terminal || ev.event === "plan" || ev.event === "answer_upgrade");
        }
      } catch (e) {
        if ((e as Error)?.name === "AbortError") return live.current;
        failWith(
          e instanceof GleanWiseError
            ? e.toBody()
            : {
                code: "error",
                message: e instanceof Error ? e.message : String(e),
                hint: null,
                action: null,
                retryable: true,
              },
        );
      } finally {
        if (abort.current === ctl) {
          abort.current = null;
          activeQuery.current = null;
        }
      }
      return live.current;
    },
    [client, push],
  );

  const ask = useCallback(
    async (req: QueryInput) => {
      abort.current?.abort();
      const ctl = new AbortController();
      abort.current = ctl;
      push({ ...startState(), phase: "connecting" }, true);
      let accepted: { queryId: string; threadId: string };
      try {
        const h = await client.query(req, { signal: ctl.signal });
        accepted = { queryId: h.queryId, threadId: h.threadId };
      } catch (e) {
        if (abort.current === ctl) abort.current = null;
        if ((e as Error)?.name === "AbortError") return live.current;
        const body =
          e instanceof GleanWiseError
            ? e.toBody()
            : {
                code: "error",
                message: e instanceof Error ? e.message : String(e),
                hint: null,
                action: null,
                retryable: true,
              };
        push({ ...live.current, phase: "error", error: body }, true);
        return live.current;
      }
      onAccepted.current?.(accepted);
      return run(accepted.queryId, accepted.threadId, ctl);
    },
    [client, push, run],
  );

  /** Follow a query that is already running (or finished): replays its events, then streams live. */
  const attach = useCallback(
    (queryId: string, threadId?: string) => {
      abort.current?.abort();
      const ctl = new AbortController();
      abort.current = ctl;
      return run(queryId, threadId, ctl);
    },
    [run],
  );

  const cancel = useCallback(async () => {
    const id = activeQuery.current;
    if (!id) return;
    try {
      await client.cancel(id);
    } catch {
      /* already finished */
    }
  }, [client]);

  const show = useCallback(
    (s: AnswerState) => {
      abort.current?.abort();
      push(s, true);
    },
    [push],
  );
  const reset = useCallback(() => {
    abort.current?.abort();
    push(initialState, true);
  }, [push]);

  const busy = !["idle", "done", "error", "cancelled"].includes(state.phase);
  onAccepted.current = options.onAccepted;
  return { state, busy, ask, attach, cancel, show, reset };
}
