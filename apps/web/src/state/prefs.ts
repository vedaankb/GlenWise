// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 Ved Buddaraju

import { useCallback, useEffect, useSyncExternalStore } from "react";
import type { Focus, Mode } from "@gleanwise/react";

export type Theme = "system" | "light" | "dark";
export const ACCENTS = ["indigo", "teal", "rose", "amber", "green", "graphite"] as const;
export type Accent = (typeof ACCENTS)[number];

interface Prefs {
  theme: Theme;
  accent: Accent;
  mode: Mode;
  focus: Focus;
}
const KEY = "gleanwise.prefs";
const DEFAULTS: Prefs = { theme: "system", accent: "indigo", mode: "quick", focus: "general" };

function read(): Prefs {
  try {
    return { ...DEFAULTS, ...(JSON.parse(localStorage.getItem(KEY) ?? "{}") as Partial<Prefs>) };
  } catch {
    return DEFAULTS;
  }
}
let current = read();
const listeners = new Set<() => void>();
const subscribe = (cb: () => void) => (listeners.add(cb), () => void listeners.delete(cb));

export function applyPrefs(p: Prefs) {
  const dark = p.theme === "dark" || (p.theme === "system" && matchMedia("(prefers-color-scheme: dark)").matches);
  const root = document.documentElement;
  root.dataset.theme = dark ? "dark" : "light";
  root.dataset.accent = p.accent;
  document.querySelector('meta[name="theme-color"]')?.setAttribute("content", dark ? "#0d0e10" : "#fafaf8");
}

export function usePrefs() {
  const prefs = useSyncExternalStore(subscribe, () => current);
  const set = useCallback((patch: Partial<Prefs>) => {
    current = { ...current, ...patch };
    localStorage.setItem(KEY, JSON.stringify(current));
    applyPrefs(current);
    listeners.forEach((l) => l());
  }, []);
  useEffect(() => {
    applyPrefs(current);
    const mq = matchMedia("(prefers-color-scheme: dark)");
    const on = () => current.theme === "system" && applyPrefs(current);
    mq.addEventListener("change", on);
    return () => mq.removeEventListener("change", on);
  }, []);
  return [prefs, set] as const;
}
