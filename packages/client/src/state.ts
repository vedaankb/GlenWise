// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 Ved Buddaraju

/**
 * One reducer, used by the React hook, the web component and the CLI, so every surface shows the
 * same thing for the same event stream.
 */
import type {
  Citation,
  DataFlowInfo,
  DoneEvent,
  ErrorBody,
  PlanEvent,
  GleanWiseEvent,
  Source,
  UsageInfo,
  VisitEvent,
  WarningEvent,
} from "./types";

export type SourceState = "found" | "reading" | "read" | "failed" | "skipped";
export interface SourceView extends Source {
  state: SourceState;
  reason?: string | null;
}

export type Phase = "idle" | "connecting" | "searching" | "reading" | "writing" | "done" | "error" | "cancelled";

export interface AnswerState {
  phase: Phase;
  queryId?: string;
  threadId?: string;
  messageId?: string | null;
  plan?: PlanEvent;
  sources: SourceView[];
  answer: string;
  /** True while the visible text is a quick snippet-based draft that will be replaced. */
  draft: boolean;
  /** True from `answer_upgrade` until the refined answer is complete. */
  refining: boolean;
  citations: Citation[];
  reasoning: string;
  visits: VisitEvent[];
  warnings: WarningEvent[];
  followUps: string[];
  usage?: UsageInfo;
  durationMs?: number;
  researchSummary?: string | null;
  dataFlow?: DataFlowInfo | null;
  error?: ErrorBody;
}

export const initialState: AnswerState = {
  phase: "idle",
  sources: [],
  answer: "",
  draft: false,
  refining: false,
  citations: [],
  reasoning: "",
  visits: [],
  warnings: [],
  followUps: [],
};

export function startState(queryId?: string, threadId?: string): AnswerState {
  return { ...initialState, phase: "connecting", queryId, threadId };
}

export function reduce(state: AnswerState, ev: GleanWiseEvent): AnswerState {
  switch (ev.event) {
    case "plan":
      return { ...state, plan: ev.data, phase: state.phase === "connecting" ? "searching" : state.phase };
    case "sources": {
      const known = new Set(state.sources.map((s) => s.id));
      const added = ev.data.sources.filter((s) => !known.has(s.id)).map((s): SourceView => ({ ...s, state: "found" }));
      return {
        ...state,
        sources: [...state.sources, ...added],
        phase: state.phase === "writing" ? "writing" : "reading",
      };
    }
    case "source_update":
      return {
        ...state,
        sources: state.sources.map((s) =>
          s.id === ev.data.id ? { ...s, state: ev.data.state, reason: ev.data.reason ?? null } : s,
        ),
      };
    case "answer_delta":
      return { ...state, phase: "writing", answer: state.answer + ev.data.text, draft: ev.data.draft ?? false };
    case "answer_upgrade":
      return { ...state, answer: "", draft: false, refining: true, citations: [] };
    case "answer_complete":
      return {
        ...state,
        answer: ev.data.text,
        citations: ev.data.citations,
        draft: false,
        refining: false,
        sources: state.sources.map((s) => ({ ...s, used_in_answer: ev.data.citations.some((c) => c.number === s.id) })),
      };
    case "follow_ups":
      return { ...state, followUps: ev.data.questions };
    case "reasoning_delta":
      return { ...state, reasoning: state.reasoning + ev.data.text };
    case "visit":
      return { ...state, visits: [...state.visits, ev.data] };
    case "warning":
      return { ...state, warnings: [...state.warnings, ev.data] };
    case "done":
      return applyDone(state, ev.data);
    case "error":
      return { ...state, phase: "error", error: ev.data, refining: false, draft: false };
    default:
      return state;
  }
}

function applyDone(state: AnswerState, d: DoneEvent): AnswerState {
  const cancelled = d.status === "cancelled";
  return {
    ...state,
    phase: cancelled ? "cancelled" : "done",
    queryId: d.query_id,
    threadId: d.thread_id,
    messageId: d.message_id,
    answer: cancelled ? state.answer : d.answer || state.answer,
    citations: cancelled ? state.citations : d.citations,
    followUps: d.follow_ups.length ? d.follow_ups : state.followUps,
    usage: d.usage,
    durationMs: d.duration_ms,
    researchSummary: d.research_summary,
    dataFlow: d.data_flow ?? state.dataFlow ?? null,
    refining: false,
    draft: false,
    sources: d.sources.length
      ? d.sources.map((s) => ({
          ...(state.sources.find((x) => x.id === s.id) ?? { state: "read" as SourceState }),
          ...s,
        }))
      : state.sources,
  };
}

/** Human-readable one-liner for what the engine is doing right now (for status regions). */
export function describePhase(s: AnswerState): string {
  switch (s.phase) {
    case "connecting":
      return "Connecting…";
    case "searching":
      return "Searching the web…";
    case "reading": {
      const reading = s.sources.filter((x) => x.state === "reading").length;
      const read = s.sources.filter((x) => x.state === "read").length;
      return reading || read ? `Reading sources (${read} of ${s.sources.length})…` : "Found sources…";
    }
    case "writing":
      return s.refining ? "Refining with full pages…" : "Writing the answer…";
    case "done":
      return "Answer ready";
    case "cancelled":
      return "Stopped";
    case "error":
      return s.error?.message ?? "Something went wrong";
    default:
      return "";
  }
}
