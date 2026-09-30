// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 Ved Buddaraju

/**
 * Ergonomic aliases over the generated `schema.d.ts` (do not edit that file — run `pnpm gen:api`).
 * Every type here comes from the server's OpenAPI document, so client and server cannot drift.
 */
import type { components } from "./schema";

type S = components["schemas"];

export type Mode = S["Mode"];
export type Focus = S["Focus"];
export type Source = S["Source"];
export type Citation = S["Citation"];
export type QueryRequest = S["QueryRequest"];
/** What callers pass: only `query` is required; every other field has a server default. */
export type QueryInput = Pick<QueryRequest, "query"> & Partial<Omit<QueryRequest, "query">>;
export type QueryAccepted = S["QueryAccepted"];
export type QueryStatus = S["QueryStatus"];
export type ThreadSummary = S["ThreadSummary"];
export type ThreadDetail = S["ThreadDetail"];
export type MessageOut = S["MessageOut"];
export type SettingsView = S["SettingsView"];
export type SettingsUpdate = S["SettingsUpdate"];
export type HealthResponse = S["HealthResponse"];
export type HealthComponent = S["HealthComponent"];
export type SetupTestResult = S["SetupTestResult"];
export type SearchResponse = S["SearchResponse"];
export type FetchResponse = S["FetchResponse"];
export type RetrieveResponse = S["RetrieveResponse"];
export type ErrorBody = S["ErrorBody"];
export type UsageInfo = S["UsageInfo"];

export type PlanEvent = S["PlanEvent"];
export type SourcesEvent = S["SourcesEvent"];
export type SourceUpdateEvent = S["SourceUpdateEvent"];
export type AnswerDeltaEvent = S["AnswerDeltaEvent"];
export type AnswerUpgradeEvent = S["AnswerUpgradeEvent"];
export type AnswerCompleteEvent = S["AnswerCompleteEvent"];
export type FollowUpsEvent = S["FollowUpsEvent"];
export type ReasoningDeltaEvent = S["ReasoningDeltaEvent"];
export type VisitEvent = S["VisitEvent"];
export type WarningEvent = S["WarningEvent"];
export type DoneEvent = S["DoneEvent"];
export type DataFlowInfo = S["DataFlowInfo"];
export type EgressActivity = S["EgressActivity"];
export type EgressEvent = S["EgressEvent"];

type Catalog = Required<{ [K in keyof S["EventCatalog"]]: NonNullable<S["EventCatalog"][K]> }>;

/** Discriminated union of everything a query stream can emit. `event` matches the SSE `event:` name. */
export type GleanWiseEvent = {
  [K in keyof Catalog]: { id: number; event: K; data: Catalog[K] };
}[keyof Catalog];

export type EventName = GleanWiseEvent["event"];
export const TERMINAL_EVENTS: readonly EventName[] = ["done", "error"];

export type ErrorAction = "open_settings" | "retry" | "open_diagnostics" | "shorten_query";
