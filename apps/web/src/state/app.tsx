// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 Ved Buddaraju

import {
  GleanWiseClient,
  GleanWiseError,
  GleanWiseProvider,
  type HealthResponse,
  type SettingsView,
  type ThreadSummary,
} from "@gleanwise/react";
import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { useT } from "@/i18n";

const TOKEN_KEY = "gleanwise.token";

export interface Toast {
  id: number;
  title: string;
  body?: string;
  tone?: "default" | "error" | "success";
  action?: { label: string; run(): void };
}

interface App {
  client: GleanWiseClient;
  settings: SettingsView | null;
  refreshSettings(): Promise<SettingsView | null>;
  health: HealthResponse | null;
  refreshHealth(): Promise<void>;
  threads: ThreadSummary[];
  threadsLoaded: boolean;
  refreshThreads(): Promise<void>;
  patchThread(id: string, patch: { title?: string; pinned?: boolean }): Promise<void>;
  removeThread(id: string): Promise<void>;
  toasts: Toast[];
  toast(t: Omit<Toast, "id">): void;
  dismissToast(id: number): void;
  /** Fatal, whole-app condition: server unreachable or a token is required. */
  gate: null | { kind: "offline"; error: GleanWiseError } | { kind: "auth"; error: GleanWiseError };
  retryConnect(): void;
  setToken(t: string | null): void;
}

const Ctx = createContext<App | null>(null);
export const useApp = () => {
  const v = useContext(Ctx);
  if (!v) throw new Error("useApp outside AppProvider");
  return v;
};

export function AppProvider({ children, client: injected }: { children: ReactNode; client?: GleanWiseClient }) {
  const t = useT();
  const client = useMemo(
    () => injected ?? new GleanWiseClient({ token: () => localStorage.getItem(TOKEN_KEY) ?? undefined }),
    [injected],
  );
  const [settings, setSettings] = useState<SettingsView | null>(null);
  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [threads, setThreads] = useState<ThreadSummary[]>([]);
  const [threadsLoaded, setLoaded] = useState(false);
  const [toasts, setToasts] = useState<Toast[]>([]);
  const [gate, setGate] = useState<App["gate"]>(null);
  const seq = useRef(0);

  const dismissToast = useCallback((id: number) => setToasts((l) => l.filter((x) => x.id !== id)), []);
  const toast = useCallback(
    (x: Omit<Toast, "id">) => {
      const id = ++seq.current;
      setToasts((l) => [...l.slice(-3), { ...x, id }]);
      window.setTimeout(() => dismissToast(id), x.action ? 9000 : x.tone === "error" ? 8000 : 4500);
    },
    [dismissToast],
  );

  const guard = useCallback(<T,>(p: Promise<T>): Promise<T | null> => {
    return p.then(
      (v) => (setGate(null), v),
      (e: unknown) => {
        if (e instanceof GleanWiseError) {
          if (e.status === 401 || e.code === "unauthorized") setGate({ kind: "auth", error: e });
          else if (e.code === "network") setGate({ kind: "offline", error: e });
          else throw e;
          return null;
        }
        throw e;
      },
    );
  }, []);

  const refreshSettings = useCallback(async () => {
    const s = await guard(client.getSettings());
    if (s) setSettings(s);
    return s;
  }, [client, guard]);

  const refreshHealth = useCallback(async () => {
    try {
      setHealth(await client.ready());
    } catch {
      /* the status dot simply stays as it was */
    }
  }, [client]);

  const refreshThreads = useCallback(async () => {
    const list = await guard(client.listThreads({ limit: 200 }));
    if (list) setThreads(list);
    setLoaded(true);
  }, [client, guard]);

  const patchThread = useCallback(
    async (id: string, patch: { title?: string; pinned?: boolean }) => {
      const before = threads;
      setThreads((l) => l.map((x) => (x.id === id ? { ...x, ...patch } : x)));
      try {
        await client.updateThread(id, patch);
      } catch (e) {
        setThreads(before);
        toast({ title: t("toast.updateFailed"), body: e instanceof Error ? e.message : undefined, tone: "error" });
      }
    },
    [client, threads, toast, t],
  );

  const removeThread = useCallback(
    async (id: string) => {
      const before = threads;
      setThreads((l) => l.filter((x) => x.id !== id));
      try {
        await client.deleteThread(id);
      } catch (e) {
        setThreads(before);
        toast({ title: t("toast.deleteFailed"), body: e instanceof Error ? e.message : undefined, tone: "error" });
      }
    },
    [client, threads, toast, t],
  );

  const boot = useCallback(() => {
    void refreshSettings().then((s) => {
      if (s) {
        void refreshThreads();
        void refreshHealth();
      }
    });
  }, [refreshSettings, refreshThreads, refreshHealth]);
  useEffect(boot, [boot]);

  const setToken = useCallback(
    (tok: string | null) => {
      if (tok) localStorage.setItem(TOKEN_KEY, tok);
      else localStorage.removeItem(TOKEN_KEY);
      boot();
    },
    [boot],
  );

  const value: App = {
    client,
    settings,
    refreshSettings,
    health,
    refreshHealth,
    threads,
    threadsLoaded,
    refreshThreads,
    patchThread,
    removeThread,
    toasts,
    toast,
    dismissToast,
    gate,
    retryConnect: boot,
    setToken,
  };
  return (
    <GleanWiseProvider client={client}>
      <Ctx.Provider value={value}>{children}</Ctx.Provider>
    </GleanWiseProvider>
  );
}
