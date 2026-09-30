// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 Ved Buddaraju

import { useCallback, useSyncExternalStore } from "react";

const KEY = "gleanwise.private";

function read(): boolean {
  try {
    return sessionStorage.getItem(KEY) === "1";
  } catch {
    return false;
  }
}

let current = typeof sessionStorage !== "undefined" ? read() : false;
const listeners = new Set<() => void>();
const subscribe = (cb: () => void) => (listeners.add(cb), () => void listeners.delete(cb));

export function clearPrivateMode() {
  try {
    sessionStorage.removeItem(KEY);
  } catch {
    /* ignore */
  }
  current = false;
  listeners.forEach((l) => l());
}

export function usePrivateMode() {
  const on = useSyncExternalStore(subscribe, () => current);
  const set = useCallback((v: boolean) => {
    current = v;
    try {
      if (v) sessionStorage.setItem(KEY, "1");
      else sessionStorage.removeItem(KEY);
    } catch {
      /* ignore */
    }
    listeners.forEach((l) => l());
  }, []);
  return [on, set] as const;
}
