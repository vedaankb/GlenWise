// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 Ved Buddaraju

import {
  useCallback,
  useEffect,
  useSyncExternalStore,
  type AnchorHTMLAttributes,
  type MouseEvent,
  type ReactNode,
} from "react";

export type Route =
  | { name: "home"; q: string | null }
  | { name: "thread"; id: string }
  | { name: "private" }
  | { name: "settings"; section: string | null }
  | { name: "diagnostics" }
  | { name: "setup" }
  | { name: "notfound"; path: string };

export function parseRoute(pathname: string, search = ""): Route {
  const p = pathname.replace(/\/+$/, "") || "/";
  const params = new URLSearchParams(search);
  if (p === "/") return { name: "home", q: params.get("q")?.trim() || null };
  if (p === "/private") return { name: "private" };
  const thread = /^\/c\/([\w-]{1,64})$/.exec(p);
  if (thread) return { name: "thread", id: thread[1] };
  if (p === "/settings") return { name: "settings", section: params.get("section") };
  if (p === "/diagnostics") return { name: "diagnostics" };
  if (p === "/setup") return { name: "setup" };
  return { name: "notfound", path: p };
}

let version = 0;
const listeners = new Set<() => void>();
const emit = () => {
  version++;
  listeners.forEach((l) => l());
};
const subscribe = (cb: () => void) => {
  listeners.add(cb);
  addEventListener("popstate", cb);
  return () => {
    listeners.delete(cb);
    removeEventListener("popstate", cb);
  };
};
const snapshot = () => `${location.pathname}${location.search}#${version}`;

export function useRoute(): Route {
  useSyncExternalStore(subscribe, snapshot);
  return parseRoute(location.pathname, location.search);
}

export interface HistoryState {
  scroll?: number;
  [k: string]: unknown;
}

/** Remember where the user was scrolled, so Back lands on the same spot. */
export function saveScroll() {
  history.replaceState({ ...(history.state as HistoryState | null), scroll: window.scrollY }, "");
}

let guard: ((to: string) => boolean) | null = null;

/** While set, in-app navigation asks first: return false to stay (e.g. to confirm losing unsaved work). */
export function useNavigationGuard(fn: ((to: string) => boolean) | null) {
  useEffect(() => {
    guard = fn;
    return () => {
      if (guard === fn) guard = null;
    };
  }, [fn]);
}

export function navigate(to: string, opts: { replace?: boolean; state?: HistoryState; force?: boolean } = {}) {
  if (guard && !opts.force && to !== `${location.pathname}${location.search}` && !guard(to)) return;
  if (!opts.replace) saveScroll();
  const same = to === `${location.pathname}${location.search}`;
  if (opts.replace || same) history.replaceState(opts.state ?? null, "", to);
  else history.pushState(opts.state ?? null, "", to);
  if (!same || opts.replace) window.scrollTo(0, 0);
  emit();
}

if (typeof history !== "undefined") history.scrollRestoration = "manual";

/** Call with `ready=true` once the page has its content; restores the saved scroll on Back/Forward, and tracks it as the user scrolls. */
export function useScrollRestoration(ready: boolean, key: string) {
  useEffect(() => {
    if (!ready) return;
    const y = (history.state as HistoryState | null)?.scroll;
    if (typeof y === "number" && y > 0) requestAnimationFrame(() => window.scrollTo(0, y));
    let timer: number | undefined;
    const onScroll = () => {
      window.clearTimeout(timer);
      timer = window.setTimeout(saveScroll, 200);
    };
    addEventListener("scroll", onScroll, { passive: true });
    addEventListener("pagehide", saveScroll);
    return () => {
      window.clearTimeout(timer);
      removeEventListener("scroll", onScroll);
      removeEventListener("pagehide", saveScroll);
    };
  }, [ready, key]);
}

export function useNavigate() {
  return useCallback(navigate, []);
}

interface LinkProps extends Omit<AnchorHTMLAttributes<HTMLAnchorElement>, "href"> {
  to: string;
  replace?: boolean;
  children?: ReactNode;
}

/** A real anchor (middle-click and "open in new tab" work) that navigates without a page load. */
export function Link({ to, replace, onClick, children, ...rest }: LinkProps) {
  const handle = (e: MouseEvent<HTMLAnchorElement>) => {
    onClick?.(e);
    if (
      e.defaultPrevented ||
      e.button !== 0 ||
      e.metaKey ||
      e.ctrlKey ||
      e.shiftKey ||
      e.altKey ||
      rest.target === "_blank"
    )
      return;
    e.preventDefault();
    navigate(to, { replace });
  };
  return (
    <a href={to} onClick={handle} {...rest}>
      {children}
    </a>
  );
}
