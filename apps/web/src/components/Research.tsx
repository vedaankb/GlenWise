// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 Ved Buddaraju

import type { AnswerState } from "@gleanwise/react";
import { Brain, Check, ChevronDown, Compass, Globe } from "lucide-react";
import { useEffect, useRef } from "react";
import { useT } from "@/i18n";
import { cn } from "@/lib/cn";
import { Spinner } from "./ui";

/** Deep mode's dedicated view: the plan, the reasoning as it streams, and every site the engine opens. */
export function ResearchPanel({
  state,
  live,
  resolveAsset,
}: {
  state: AnswerState;
  live: boolean;
  resolveAsset(p: string): string;
}) {
  const t = useT();
  const log = useRef<HTMLDivElement>(null);
  const lines = state.reasoning.split("\n").filter(Boolean);
  const stick = useRef(true);
  useEffect(() => {
    const el = log.current;
    if (el && stick.current) el.scrollTop = el.scrollHeight;
  }, [lines.length, state.visits.length]);

  const byId = new Map(state.sources.map((s) => [s.id, s]));
  const body = (
    <div className="grid gap-5 md:grid-cols-2">
      <section aria-label={t("deep.reasoning")}>
        <h3 className="mb-2 flex items-center gap-2 text-xs font-semibold tracking-wide text-muted">
          <Brain className="size-3.5" aria-hidden />
          {t("deep.reasoning")}
        </h3>
        <div
          ref={log}
          onScroll={(e) => {
            const el = e.currentTarget;
            stick.current = el.scrollHeight - el.scrollTop - el.clientHeight < 24;
          }}
          tabIndex={0}
          role="log"
          aria-live="off"
          aria-label={t("deep.reasoning")}
          className="max-h-56 space-y-1.5 overflow-y-auto rounded-[var(--radius)] bg-surface-2 p-3 text-[13px] leading-relaxed text-muted"
        >
          {lines.length ? (
            lines.map((l, i) => (
              <p key={i} className={cn("m-0", l.startsWith("Round") && "font-medium text-fg")}>
                {l}
              </p>
            ))
          ) : (
            <p className="m-0">{t("deep.planning")}</p>
          )}
        </div>
      </section>
      <section aria-label={t("deep.visited")}>
        <h3 className="mb-2 flex items-center gap-2 text-xs font-semibold tracking-wide text-muted">
          <Globe className="size-3.5" aria-hidden />
          {t("deep.visited")} <span className="tabular">({state.visits.length})</span>
        </h3>
        <ul className="max-h-56 space-y-1 overflow-y-auto pe-1" tabIndex={0} aria-label={t("deep.visited")}>
          {state.visits.map((v, i) => {
            const s = byId.get(v.source_id);
            return (
              <li
                key={`${v.source_id}-${i}`}
                className="rise flex items-center gap-2 rounded-lg px-2 py-1.5 text-[13px] hover:bg-surface-2"
              >
                {s?.favicon ? (
                  <img src={resolveAsset(s.favicon)} alt="" width={16} height={16} className="rounded-[4px]" />
                ) : (
                  <span className="size-4 rounded-[4px] bg-surface-3" aria-hidden />
                )}
                <span className="min-w-0 flex-1">
                  <span className="block truncate font-medium">{v.title || s?.title || v.url}</span>
                  <span className="block truncate text-xs text-muted">{s?.domain}</span>
                </span>
                {v.round != null ? <span className="text-xs text-subtle tabular">R{v.round}</span> : null}
              </li>
            );
          })}
          {!state.visits.length ? <li className="px-2 py-1.5 text-[13px] text-muted">{t("deep.noVisits")}</li> : null}
        </ul>
      </section>
    </div>
  );

  if (live)
    return (
      <div className="card rise p-4 sm:p-5" aria-label={t("deep.title")}>
        <div className="mb-4 flex items-center gap-2.5">
          <span className="grid size-8 place-items-center rounded-full bg-accent/12 text-accent-text">
            <Compass className="size-4" aria-hidden />
          </span>
          <div className="min-w-0 flex-1">
            <h2 className="m-0 text-[15px] font-semibold tracking-tight">{t("deep.title")}</h2>
            <p className="m-0 text-[13px] text-muted">{t("deep.slow")}</p>
          </div>
          <Spinner className="text-accent-text" />
        </div>
        {state.plan?.steps.length ? (
          <ol className="mb-4 flex flex-wrap gap-x-4 gap-y-1 text-[13px] text-muted">
            {state.plan.steps.map((s, i) => (
              <li key={i} className="flex items-center gap-1.5">
                <span className="grid size-4 place-items-center rounded-full bg-surface-3 text-[10px] font-semibold tabular">
                  {i + 1}
                </span>
                {s}
              </li>
            ))}
          </ol>
        ) : null}
        {body}
      </div>
    );

  return (
    <details className="card group px-4 py-3">
      <summary className="flex list-none items-center gap-2.5 text-sm font-medium [&::-webkit-details-marker]:hidden">
        <Check className="size-4 text-success" aria-hidden />
        <span className="flex-1">
          {t("deep.done")}
          {state.researchSummary ? <span className="ms-2 font-normal text-muted">{state.researchSummary}</span> : null}
        </span>
        <ChevronDown className="size-4 text-muted transition-transform group-open:rotate-180" aria-hidden />
      </summary>
      <div className="mt-4">{body}</div>
    </details>
  );
}
