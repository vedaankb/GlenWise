// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 Ved Buddaraju

import type { Mode } from "@gleanwise/react";
import { Lock, Trash2 } from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";
import { Composer, type ComposerHandle } from "@/components/Composer";
import { Turn, type TurnData } from "@/components/Turn";
import { Button, ConfirmDialog } from "@/components/ui";
import { useI18n } from "@/i18n";
import { uid } from "@/lib/id";
import { navigate, useNavigationGuard } from "@/router";
import { useActive } from "@/state/active";
import { usePrefs } from "@/state/prefs";
import { clearPrivateMode, usePrivateMode } from "@/state/private";

/** In-memory private session (D6): nothing is written to history, cache, or operator surfaces. */
export function PrivatePage({ composerRef }: { composerRef: React.RefObject<ComposerHandle | null> }) {
  const { t, locale } = useI18n();
  const { active, state: liveState, finished, start, stop, ack } = useActive();
  const [prefs, setPrefs] = usePrefs();
  const [, setPrivate] = usePrivateMode();
  const [turns, setTurns] = useState<TurnData[]>([]);
  const [value, setValue] = useState("");
  const [forgetOpen, setForgetOpen] = useState(false);
  const dirty = turns.length > 0 || !!active?.private;
  const [pendingTo, setPendingTo] = useState<string | null>(null);

  // In-app links away from a private session with content ask first (reload is covered below).
  const guard = useMemo(
    () =>
      dirty
        ? (to: string) => {
            setPendingTo(to);
            setForgetOpen(true);
            return false;
          }
        : null,
    [dirty],
  );
  useNavigationGuard(guard);

  useEffect(() => {
    setPrivate(true);
    document.title = `${t("private.title")} · ${t("app.name")}`;
    return () => void (document.title = t("app.name"));
  }, [setPrivate, t]);

  useEffect(() => {
    if (!dirty) return;
    const warn = (e: BeforeUnloadEvent) => e.preventDefault();
    addEventListener("beforeunload", warn);
    return () => removeEventListener("beforeunload", warn);
  }, [dirty]);

  useEffect(() => {
    if (!finished?.turn) return;
    if (finished.threadId && finished.threadId !== "ephemeral") return;
    const { turn, replaces, failed } = finished;
    setTurns((prev) => {
      if (prev.some((x) => x.id === turn.id)) return prev;
      if (failed && replaces) return prev;
      return replaces ? prev.map((x) => (x.id === replaces.id ? turn : x)) : [...prev, turn];
    });
    ack(turn.id);
  }, [finished, ack]);

  const mineActive = active?.private ? active : null;
  const shownTurns = useMemo(() => {
    const liveTurn: TurnData | null = mineActive
      ? {
          id: mineActive.id,
          query: mineActive.query,
          mode: mineActive.mode,
          live: true,
          state: liveState,
          messageId: null,
        }
      : null;
    if (!liveTurn) return turns;
    const replacesId = mineActive?.replaces?.id;
    const at = replacesId ? turns.findIndex((x) => x.id === replacesId) : -1;
    return at >= 0 ? turns.map((x, i) => (i === at ? liveTurn : x)) : [...turns, liveTurn];
  }, [turns, mineActive, liveState]);

  const send = useCallback(
    (query: string, mode: Mode, replaces?: TurnData) => {
      const q = query.trim();
      if (!q || active) return;
      const history = turns.flatMap((turn) => [
        { role: "user" as const, content: turn.query },
        { role: "assistant" as const, content: turn.state.answer },
      ]);
      start(
        {
          query: q,
          mode,
          focus: prefs.focus,
          locale,
          private: true,
          persist: false,
          history: history.length ? history : undefined,
        },
        { id: uid(), query: q, mode, focus: prefs.focus, replaces, private: true },
      );
      setValue("");
    },
    [active, start, prefs.focus, locale, turns],
  );

  const forget = () => {
    stop();
    setTurns([]);
    clearPrivateMode();
    setPrivate(false);
    navigate(pendingTo ?? "/", { replace: true, force: true });
  };

  const leave = () => {
    if (dirty) setForgetOpen(true);
    else {
      clearPrivateMode();
      setPrivate(false);
      navigate("/", { force: true });
    }
  };

  return (
    <div className="mx-auto w-full max-w-[68rem] px-5 sm:px-8">
      <header className="flex flex-wrap items-center gap-3 pt-6 pb-4 lg:pt-8">
        <span className="inline-flex items-center gap-1.5 rounded-full bg-surface-2 px-3 py-1 text-[13px] font-medium text-fg">
          <Lock className="size-3.5" aria-hidden />
          {t("private.badge")}
        </span>
        <p className="m-0 min-w-[14rem] flex-1 basis-full text-[13px] text-muted sm:basis-0">{t("private.hint")}</p>
        <Button size="sm" variant="ghost" onClick={leave}>
          {t("private.exit")}
        </Button>
        <Button size="sm" variant="danger" onClick={() => setForgetOpen(true)}>
          <Trash2 className="size-3.5" />
          {t("private.forget")}
        </Button>
      </header>

      <div className="space-y-10 pb-36">
        {shownTurns.length === 0 ? <p className="py-16 text-center text-muted">{t("private.empty")}</p> : null}
        {shownTurns.map((turn) => (
          <Turn
            key={turn.id}
            turn={turn}
            onFollowUp={(q) => send(q, prefs.mode)}
            onRegenerate={(tr, mode) => send(tr.query, mode, tr)}
            onRetry={(tr) => send(tr.query, tr.mode, tr)}
            onEditQuery={(tr) => {
              setValue(tr.query);
              composerRef.current?.focus();
            }}
          />
        ))}
      </div>

      <div className="fixed inset-x-0 bottom-0 z-10 border-t border-border bg-bg/90 px-5 py-3 backdrop-blur sm:px-8">
        <div className="mx-auto max-w-[46rem]">
          <Composer
            ref={composerRef}
            privateMode
            label={t("composer.label")}
            placeholder={t("composer.placeholder")}
            value={value}
            onChange={setValue}
            onSubmit={() => send(value, prefs.mode)}
            mode={prefs.mode}
            onMode={(mode) => setPrefs({ mode })}
            focusMode={prefs.focus}
            onFocusMode={(focus) => setPrefs({ focus })}
            busy={!!active}
            onStop={stop}
            autoFocus
          />
        </div>
      </div>

      <ConfirmDialog
        open={forgetOpen}
        onOpenChange={(o) => {
          setForgetOpen(o);
          if (!o) setPendingTo(null);
        }}
        danger
        title={t("private.forget.title")}
        body={t("private.forget.body")}
        confirmLabel={t("private.forget")}
        onConfirm={forget}
      />
    </div>
  );
}
