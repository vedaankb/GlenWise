// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 Ved Buddaraju

import { useEffect } from "react";
import { useActive } from "@/state/active";

/**
 * Softly moving, slowly colour-shifting light behind the app. Purely decorative (aria-hidden,
 * pointer-transparent). While an answer is being researched the page brightens; elements marked
 * `.glow` also catch a spotlight that follows the pointer.
 */
export function Ambient() {
  const { active } = useActive();
  const busy = !!active;

  useEffect(() => {
    const root = document.documentElement;
    if (busy) root.dataset.busy = "";
    else delete root.dataset.busy;
    return () => {
      delete root.dataset.busy;
    };
  }, [busy]);

  useEffect(() => {
    let raf = 0;
    const move = (e: PointerEvent) => {
      if (e.pointerType === "touch") return;
      const el = (e.target as Element | null)?.closest?.<HTMLElement>(".glow");
      if (!el) return;
      cancelAnimationFrame(raf);
      raf = requestAnimationFrame(() => {
        const r = el.getBoundingClientRect();
        el.style.setProperty("--mx", `${e.clientX - r.left}px`);
        el.style.setProperty("--my", `${e.clientY - r.top}px`);
      });
    };
    document.addEventListener("pointermove", move, { passive: true });
    return () => {
      document.removeEventListener("pointermove", move);
      cancelAnimationFrame(raf);
    };
  }, []);

  return (
    <div className="ambient" aria-hidden="true">
      <i className="orb orb-1" />
      <i className="orb orb-2" />
      <i className="orb orb-3" />
      <i className="orb orb-4" />
      <i className="orb orb-live" />
      <i className="grain" />
    </div>
  );
}
