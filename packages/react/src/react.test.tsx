// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 Ved Buddaraju

import { act, renderHook, waitFor } from "@testing-library/react";
import { createElement, type ReactNode } from "react";
import { describe, expect, it, vi } from "vitest";
import { GleanWiseError, type GleanWiseClient, type GleanWiseEvent } from "@gleanwise/client";
import { GleanWiseProvider, useAnswer } from "./index";

function fakeClient(events: GleanWiseEvent[], opts: { failQuery?: GleanWiseError } = {}) {
  const client = {
    query: vi.fn(async () => {
      if (opts.failQuery) throw opts.failQuery;
      return { queryId: "q1", threadId: "t1" };
    }),
    streamEvents: vi.fn(async function* () {
      for (const e of events) yield e;
    }),
    cancel: vi.fn(async () => undefined),
  };
  const wrapper = ({ children }: { children: ReactNode }) =>
    createElement(GleanWiseProvider, { client: client as unknown as GleanWiseClient }, children);
  return { client, wrapper };
}

const ev = (event: string, data: object): GleanWiseEvent => ({ event, data, id: "1" }) as unknown as GleanWiseEvent;

describe("useAnswer", () => {
  it("streams an answer to completion and reports the accepted query first", async () => {
    const { wrapper } = fakeClient([
      ev("answer_delta", { text: "Hello " }),
      ev("answer_delta", { text: "world" }),
      ev("done", {
        status: "done",
        query_id: "q1",
        thread_id: "t1",
        message_id: "m1",
        answer: "Hello world",
        citations: [],
        follow_ups: [],
        sources: [],
        usage: {},
        duration_ms: 5,
      }),
    ]);
    const accepted = vi.fn();
    const { result } = renderHook(() => useAnswer({ onAccepted: accepted }), { wrapper });
    await act(async () => {
      await result.current.ask({ query: "hi" });
    });
    expect(accepted).toHaveBeenCalledWith({ queryId: "q1", threadId: "t1" });
    await waitFor(() => expect(result.current.state.phase).toBe("done"));
    expect(result.current.state.answer).toBe("Hello world");
    expect(result.current.busy).toBe(false);
  });

  it("surfaces a rejected query as an actionable error state", async () => {
    const err = new GleanWiseError(
      {
        code: "llm_not_configured",
        message: "No model configured.",
        hint: "Choose a model.",
        action: "open_settings",
        retryable: false,
      },
      400,
    );
    const { wrapper } = fakeClient([], { failQuery: err });
    const { result } = renderHook(() => useAnswer(), { wrapper });
    await act(async () => {
      await result.current.ask({ query: "hi" });
    });
    expect(result.current.state.phase).toBe("error");
    expect(result.current.state.error?.action).toBe("open_settings");
  });

  it("throws a helpful error outside a provider", () => {
    expect(() => renderHook(() => useAnswer())).toThrow(/GleanWiseProvider/);
  });
});
