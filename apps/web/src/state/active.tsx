// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 Ved Buddaraju

import { GleanWiseError, useAnswer, type AnswerState, type Focus, type Mode, type QueryInput } from "@gleanwise/react";
import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import type { TurnData } from "@/components/Turn";
import { useApp } from "./app";

export interface ActiveMeta {
  id: string;
  query: string;
  mode: Mode;
  focus: Focus;
  /** Set when this run regenerates an existing answer. */
  replaces?: TurnData;
  /** D6 private session — in-memory only. */
  private?: boolean;
}
export interface ActiveQuery extends ActiveMeta {
  threadId: string | null;
  queryId: string | null;
}
export interface Finished {
  threadId: string | null;
  turn: TurnData;
  replaces?: TurnData;
  failed: boolean;
}

interface Ctx {
  active: ActiveQuery | null;
  /** Live state of the running query (only meaningful while `active`). */
  state: AnswerState;
  finished: Finished | null;
  start(req: QueryInput, meta: ActiveMeta, onAccepted?: (q: { queryId: string; threadId: string }) => void): void;
  stop(): void;
  ack(turnId: string): void;
}
const ActiveCtx = createContext<Ctx | null>(null);
export const useActive = () => {
  const v = useContext(ActiveCtx);
  if (!v) throw new Error("useActive outside ActiveProvider");
  return v;
};

const STORE = "gleanwise.active";

/**
 * Owns the one running query for the whole app, so navigating between pages never drops the stream,
 * and a page reload re-attaches to a query that is still running on the server.
 */
export function ActiveProvider({ children }: { children: ReactNode }) {
  const { client, refreshThreads } = useApp();
  const acceptedCb = useRef<((q: { queryId: string; threadId: string }) => void) | undefined>(undefined);
  const activeRef = useRef<ActiveQuery | null>(null);
  const [active, setActiveState] = useState<ActiveQuery | null>(null);
  const [finished, setFinished] = useState<Finished | null>(null);
  const setActive = useCallback((a: ActiveQuery | null) => {
    activeRef.current = a;
    setActiveState(a);
  }, []);

  const answer = useAnswer({
    onAccepted: (q) => {
      const cur = activeRef.current;
      if (cur) {
        const next = { ...cur, threadId: q.threadId, queryId: q.queryId };
        setActive(next);
        if (!next.private) {
          const { replaces: _drop, ...persist } = next;
          sessionStorage.setItem(STORE, JSON.stringify(persist));
        }
      }
      acceptedCb.current?.(q);
      acceptedCb.current = undefined;
    },
  });

  const finish = useCallback(
    (state: AnswerState) => {
      const meta = activeRef.current;
      if (!meta) return;
      sessionStorage.removeItem(STORE);
      const failed = state.phase === "error";
      setFinished({
        threadId: state.threadId ?? meta.threadId,
        replaces: meta.replaces,
        failed,
        turn: {
          id: meta.id,
          query: meta.query,
          mode: meta.mode,
          live: false,
          state,
          messageId: state.messageId ?? null,
        },
      });
      setActive(null);
      void refreshThreads();
    },
    [refreshThreads, setActive],
  );

  const { ask, attach, cancel } = answer;
  const start = useCallback<Ctx["start"]>(
    (req, meta, onAccepted) => {
      acceptedCb.current = onAccepted;
      setFinished(null);
      setActive({ ...meta, threadId: req.thread_id ?? null, queryId: null });
      void ask(req).then(finish);
    },
    [ask, finish, setActive],
  );

  const stop = useCallback(() => void cancel(), [cancel]);
  const ack = useCallback((turnId: string) => setFinished((f) => (f && f.turn.id === turnId ? null : f)), []);

  // After a reload, pick a still-running query back up.
  const resumed = useRef(false);
  useEffect(() => {
    if (resumed.current) return;
    resumed.current = true;
    const raw = sessionStorage.getItem(STORE);
    if (!raw) return;
    let saved: ActiveQuery;
    try {
      saved = JSON.parse(raw) as ActiveQuery;
    } catch {
      sessionStorage.removeItem(STORE);
      return;
    }
    if (!saved.queryId) {
      sessionStorage.removeItem(STORE);
      return;
    }
    const queryId = saved.queryId;
    client.status(queryId).then(
      (st) => {
        if (st.status === "queued" || st.status === "running") {
          setActive(saved);
          void attach(queryId, saved.threadId ?? undefined).then(finish);
        } else sessionStorage.removeItem(STORE);
      },
      (e: unknown) => {
        if (e instanceof GleanWiseError && e.code !== "network") sessionStorage.removeItem(STORE);
      },
    );
  }, [client, attach, finish, setActive]);

  const value = useMemo<Ctx>(
    () => ({ active, state: answer.state, finished, start, stop, ack }),
    [active, answer.state, finished, start, stop, ack],
  );
  return <ActiveCtx.Provider value={value}>{children}</ActiveCtx.Provider>;
}
