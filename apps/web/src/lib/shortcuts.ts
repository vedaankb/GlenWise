// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 Ved Buddaraju

import { useEffect } from "react";

const isTyping = (t: EventTarget | null) => {
  const el = t as HTMLElement | null;
  return !!el && (el.isContentEditable || ["INPUT", "TEXTAREA", "SELECT"].includes(el.tagName));
};

export interface Shortcuts {
  newThread(): void;
  focusSearch(): void;
  setMode(i: 0 | 1 | 2): void;
  help(): void;
}

/** ⌘/Ctrl+K new thread · / focus search · Alt+1/2/3 mode · ? help. Never fires while typing (except ⌘K and Alt combos). */
export function useShortcuts(s: Shortcuts) {
  useEffect(() => {
    const on = (e: KeyboardEvent) => {
      if (e.isComposing) return;
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        return s.newThread();
      }
      if (
        e.altKey &&
        !e.metaKey &&
        !e.ctrlKey &&
        ["1", "2", "3"].includes(e.code.slice(-1)) &&
        e.code.startsWith("Digit")
      ) {
        e.preventDefault();
        return s.setMode((Number(e.code.slice(-1)) - 1) as 0 | 1 | 2);
      }
      if (isTyping(e.target) || e.metaKey || e.ctrlKey || e.altKey) return;
      if (e.key === "/") {
        e.preventDefault();
        s.focusSearch();
      } else if (e.key === "?") {
        e.preventDefault();
        s.help();
      }
    };
    addEventListener("keydown", on);
    return () => removeEventListener("keydown", on);
  }, [s]);
}
