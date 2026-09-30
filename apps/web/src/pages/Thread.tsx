// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 Ved Buddaraju

import { cn } from "@/lib/cn";
import {
  stateFromMessage,
  GleanWiseError,
  type AnswerState,
  type MessageOut,
  type Mode,
  initialState,
} from "@gleanwise/react";
import { Pencil } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Composer, type ComposerHandle } from "@/components/Composer";
import { Turn, type TurnData } from "@/components/Turn";
import { Button, Spinner } from "@/components/ui";
import { useI18n } from "@/i18n";
import { uid } from "@/lib/id";
import { Link, navigate, useScrollRestoration } from "@/router";
import { useActive } from "@/state/active";
import { useApp } from "@/state/app";
import { usePrefs } from "@/state/prefs";

function pair(messages: MessageOut[]): TurnData[] {
  const out: TurnData[] = [];
  let pending: MessageOut | null = null;
  for (const m of messages) {
    if (m.role === "user") {
      pending = m;
      continue;
    }
    out.push({
      id: m.id,
      query: pending?.content ?? "",
      mode: m.mode ?? "quick",
      state: stateFromMessage(m),
      live: false,
      messageId: m.id,
    });
    pending = null;
  }
  return out;
}

type Load = "loading" | "ready" | "missing" | "error";

export function ThreadPage({ id, composerRef }: { id: string; composerRef: React.RefObject<ComposerHandle | null> }) {
  const { t, locale } = useI18n();
  const { client, threads, patchThread, toast } = useApp();
  const { active, state: liveState, finished, start, stop, ack } = useActive();
  const [prefs, setPrefs] = usePrefs();
  const [load, setLoad] = useState<Load>("loading");
  const [turns, setTurns] = useState<TurnData[]>([]);
  const [title, setTitle] = useState("");
  const [value, setValue] = useState("");
  const [editingTitle, setEditingTitle] = useState(false);
  const [loadError, setLoadError] = useState<GleanWiseError | null>(null);

  const load_ = useCallback(async () => {
    try {
      const d = await client.getThread(id);
      setTurns(pair(d.messages));
      setTitle(d.title);
      setLoad("ready");
    } catch (e) {
      if (e instanceof GleanWiseError && (e.status === 404 || e.code === "not_found")) setLoad("missing");
      else {
        setLoadError(e instanceof GleanWiseError ? e : null);
        setLoad("error");
      }
    }
  }, [client, id]);

  useEffect(() => {
    setLoad("loading");
    setTurns([]);
    setValue("");
    void load_();
  }, [load_]);

  // A thread we just created has no messages yet while its first answer streams; that is normal.
  const mineActive = active && active.threadId === id ? active : null;
  const busyElsewhere = !!active && active.threadId !== id;

  // Fold a finished run into the list (replacing the answer it regenerated, if any).
  useEffect(() => {
    if (!finished || finished.threadId !== id || load !== "ready") return;
    const { turn, replaces, failed } = finished;
    setTurns((prev) => {
      if (prev.some((x) => x.id === turn.id)) return prev;
      if (failed && replaces) return prev; // keep the answer we tried to replace
      return replaces ? prev.map((x) => (x.id === replaces.id ? turn : x)) : [...prev, turn];
    });
    if (failed && replaces) {
      const e = turn.state.error;
      toast({ title: e?.message ?? t("toast.regenerateFailed"), body: e?.hint ?? undefined, tone: "error" });
    }
    ack(turn.id);
  }, [finished, id, load, ack, toast, t]);

  const shownTurns = useMemo(() => {
    const liveTurn: TurnData | null = mineActive
      ? {
          id: mineActive.id,
          query: mineActive.query,
          mode: mineActive.mode,
          live: true,
          state: liveState.phase === "idle" ? initialState : liveState,
          messageId: null,
        }
      : null;
    const unfolded =
      !liveTurn &&
      finished &&
      finished.threadId === id &&
      !turns.some((x) => x.id === finished.turn.id) &&
      !(finished.failed && finished.replaces)
        ? finished.turn
        : null;
    const extra = liveTurn ?? unfolded;
    if (!extra) return turns;
    const replacesId = liveTurn ? mineActive?.replaces?.id : finished?.replaces?.id;
    const at = replacesId ? turns.findIndex((x) => x.id === replacesId) : -1;
    return at >= 0 ? turns.map((x, i) => (i === at ? extra : x)) : [...turns, extra];
  }, [turns, mineActive, liveState, finished, id]);

  const send = useCallback(
    (query: string, mode: Mode, replaces?: TurnData) => {
      const q = query.trim();
      if (!q || active) return;
      start(
        {
          query: q,
          thread_id: id,
          mode,
          focus: prefs.focus,
          locale,
          regenerate_message_id: replaces?.messageId ?? undefined,
        },
        { id: uid(), query: q, mode, focus: prefs.focus, replaces },
      );
      setValue("");
    },
    [active, start, id, prefs.focus, locale],
  );

  // Title + document title.
  const threadTitle = threads.find((x) => x.id === id)?.title ?? title;
  useEffect(() => {
    document.title = `${threadTitle || t("thread.untitled")} · ${t("app.name")}`;
    return () => void (document.title = t("app.name"));
  }, [threadTitle, t]);

  // Scroll: restore on Back; and announce progress to assistive tech once per phase.
  useScrollRestoration(load === "ready", id);
  const announce = useMemo(() => {
    if (!mineActive) return "";
    const p = liveState.phase;
    if (p === "connecting" || p === "searching") return t("live.searching");
    if (p === "reading") return t("live.reading");
    if (p === "writing") return liveState.refining ? t("live.upgrading") : t("live.writing");
    return "";
  }, [mineActive, liveState.phase, liveState.refining, t]);
  const [doneNote, setDoneNote] = useState("");
  useEffect(() => {
    if (finished?.threadId === id)
      setDoneNote(finished.failed ? (finished.turn.state.error?.message ?? "") : t("live.done"));
  }, [finished, id, t]);

  const heading = useRef<HTMLHeadingElement>(null);
  useEffect(() => {
    if (load === "ready" && !mineActive) heading.current?.focus({ preventScroll: true });
  }, [load, id]); // eslint-disable-line react-hooks/exhaustive-deps

  if (load === "loading")
    return (
      <div className="mx-auto max-w-5xl px-5 py-10" aria-busy="true">
        <div className="skeleton mb-4 h-8 w-2/3" />
        <div className="grid gap-10 lg:grid-cols-[2fr_1fr]">
          <div className="space-y-3">
            {[95, 88, 92, 60].map((w) => (
              <div key={w} className="skeleton h-4" style={{ inlineSize: `${w}%` }} />
            ))}
          </div>
          <div className="space-y-4">
            {[0, 1, 2].map((i) => (
              <div key={i} className="skeleton h-14" />
            ))}
          </div>
        </div>
        <span className="sr-only" role="status">
          <Spinner /> {t("common.loading")}
        </span>
      </div>
    );

  if (load === "missing")
    return (
      <div className="mx-auto flex min-h-[60dvh] max-w-md flex-col items-center justify-center gap-3 px-5 text-center">
        <h1 className="m-0 text-2xl font-semibold tracking-tight">{t("thread.missing.title")}</h1>
        <p className="m-0 text-muted">{t("thread.missing.body")}</p>
        <Link to="/" className="btn btn-primary mt-2">
          {t("thread.missing.cta")}
        </Link>
      </div>
    );

  if (load === "error")
    return (
      <div
        className="mx-auto flex min-h-[60dvh] max-w-md flex-col items-center justify-center gap-3 px-5 text-center"
        role="alert"
      >
        <h1 className="m-0 text-2xl font-semibold tracking-tight">{t("thread.loadFailed")}</h1>
        <p className="m-0 text-muted">{loadError?.hint ?? loadError?.message}</p>
        <Button variant="primary" onClick={() => void load_()}>
          {t("error.retry")}
        </Button>
      </div>
    );

  const redundantTitle = shownTurns.length === 1 && threadTitle.trim() === shownTurns[0].query.trim();

  return (
    <div className="mx-auto w-full max-w-[68rem] px-5 sm:px-8">
      <header className="flex items-center gap-2 pt-6 pb-4 lg:pt-8">
        {editingTitle ? (
          <input
            autoFocus
            defaultValue={threadTitle}
            aria-label={t("thread.rename")}
            className="field !min-h-9 max-w-md !py-1 text-sm"
            maxLength={200}
            onBlur={(e) => {
              setEditingTitle(false);
              const next = e.currentTarget.value.trim();
              if (next && next !== threadTitle) {
                setTitle(next);
                void patchThread(id, { title: next });
              }
            }}
            onKeyDown={(e) => {
              if (e.key === "Enter") e.currentTarget.blur();
              if (e.key === "Escape") setEditingTitle(false);
            }}
          />
        ) : (
          <>
            <h1
              ref={heading}
              tabIndex={-1}
              className={cn(
                "m-0 min-w-0 truncate text-[13px] font-medium text-muted outline-none",
                // The first question is already the visible heading below, so don't say it twice.
                redundantTitle && "sr-only",
              )}
            >
              {threadTitle || t("thread.untitled")}
            </h1>
            <button
              type="button"
              className={cn("btn btn-ghost btn-sm btn-icon", redundantTitle && "ms-auto")}
              aria-label={t("thread.rename")}
              onClick={() => setEditingTitle(true)}
            >
              <Pencil className="size-3.5" />
            </button>
          </>
        )}
      </header>

      <div role="status" aria-live="polite" className="sr-only">
        {announce || doneNote}
      </div>

      <div className="space-y-10">
        {shownTurns.length === 0 ? <p className="py-16 text-center text-muted">{t("thread.empty")}</p> : null}
        {shownTurns.map((turn) => (
          <Turn
            key={turn.id}
            turn={turn}
            threadId={id}
            onFollowUp={(q) => send(q, prefs.mode)}
            onRegenerate={(tn, mode) => send(tn.query, mode, tn)}
            onRetry={(tn) => send(tn.query, tn.mode, tn.messageId ? tn : undefined)}
            onEditQuery={(tn) => {
              setValue(tn.query);
              composerRef.current?.focus();
            }}
          />
        ))}
      </div>

      <div className="pointer-events-none sticky bottom-0 z-10 -mx-5 mt-8 bg-gradient-to-t from-bg from-60% to-transparent px-5 pt-8 pb-4 sm:-mx-8 sm:px-8">
        <div className="pointer-events-auto mx-auto max-w-[46rem]">
          {busyElsewhere ? (
            <p className="mb-2 text-center text-[13px] text-muted">
              {t("thread.busyElsewhere", { query: active?.query ?? "" })}
            </p>
          ) : null}
          <Composer
            ref={composerRef}
            label={t("composer.followUp")}
            placeholder={t("composer.followUp.placeholder")}
            value={value}
            onChange={setValue}
            onSubmit={() => send(value, prefs.mode)}
            mode={prefs.mode}
            onMode={(mode) => setPrefs({ mode })}
            focusMode={prefs.focus}
            onFocusMode={(focus) => setPrefs({ focus })}
            busy={!!active}
            onStop={stop}
          />
        </div>
      </div>
    </div>
  );
}

export { navigate };
export type { AnswerState };
