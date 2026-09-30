// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 Ved Buddaraju

import { useEffect, useRef, useState } from "react";
import { Composer, type ComposerHandle } from "@/components/Composer";
import { ErrorNotice } from "@/components/Notices";
import { useT } from "@/i18n";
import { useI18n } from "@/i18n";
import { uid } from "@/lib/id";
import { Link, navigate, useRoute } from "@/router";
import { useActive } from "@/state/active";
import { useApp } from "@/state/app";
import { usePrefs } from "@/state/prefs";
import { ArrowRight, Sparkles } from "lucide-react";

const STARTERS = ["home.try1", "home.try2", "home.try3"] as const;

export function HomePage({ composerRef }: { composerRef: React.RefObject<ComposerHandle | null> }) {
  const t = useT();
  const { locale } = useI18n();
  const { settings } = useApp();
  const { active, start, stop, finished } = useActive();
  const route = useRoute();
  const [prefs, setPrefs] = usePrefs();
  const [value, setValue] = useState(route.name === "home" ? (route.q ?? "") : "");
  const busy = !!active;

  const submit = (query = value) => {
    const q = query.trim();
    if (!q || busy) return;
    start(
      { query: q, mode: prefs.mode, focus: prefs.focus, locale },
      { id: uid(), query: q, mode: prefs.mode, focus: prefs.focus },
      (acc) => {
        setValue("");
        navigate(`/c/${acc.threadId}`);
      },
    );
  };

  // Registered as a browser search engine (see /opensearch.xml): "/?q=…" searches immediately.
  const auto = useRef(false);
  useEffect(() => {
    if (auto.current || route.name !== "home" || !route.q || !settings?.configured) return;
    auto.current = true;
    navigate("/", { replace: true });
    submit(route.q);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [route, settings?.configured]);

  const error = finished && !finished.threadId && finished.failed ? finished.turn.state.error : undefined;

  return (
    <div className="mx-auto flex min-h-[calc(100dvh-4rem)] w-full max-w-[46rem] flex-col justify-center px-5 pb-24 lg:min-h-dvh">
      <h1 className="rise gild mb-8 pb-1 text-center text-[36px] leading-[1.15] tracking-[-0.025em] text-balance sm:text-[52px]">
        {t("home.title")}
      </h1>
      <div className="rise" style={{ animationDelay: "60ms" }}>
        <Composer
          ref={composerRef}
          variant="hero"
          autoFocus
          label={t("composer.label")}
          placeholder={t("composer.placeholder")}
          value={value}
          onChange={setValue}
          onSubmit={() => submit()}
          mode={prefs.mode}
          onMode={(mode) => setPrefs({ mode })}
          focusMode={prefs.focus}
          onFocusMode={(focus) => setPrefs({ focus })}
          busy={busy}
          onStop={stop}
        />
      </div>
      <div className="mt-4 min-h-6 text-center text-[13px] text-muted">
        {busy ? t("home.starting") : t("composer.hint")}
      </div>
      {settings?.configured && !busy ? (
        <ul className="stagger m-0 mt-5 flex list-none flex-wrap justify-center gap-2 p-0" aria-label={t("home.try")}>
          {STARTERS.map((k, i) => (
            <li key={k} style={{ "--i": i + 2 } as React.CSSProperties}>
              <button type="button" className="chip glow" onClick={() => submit(t(k))}>
                <Sparkles className="size-3.5" aria-hidden />
                {t(k)}
              </button>
            </li>
          ))}
        </ul>
      ) : null}
      {settings && !settings.configured ? (
        <div className="card mx-auto mt-6 flex max-w-md items-center gap-4 p-4">
          <div className="flex-1 text-sm">
            <p className="m-0 font-semibold">{t("home.setup.title")}</p>
            <p className="m-0 text-muted">{t("home.setup.body")}</p>
          </div>
          <Link to="/setup" className="btn btn-primary btn-sm">
            {t("home.setup.cta")}
            <ArrowRight className="size-4 rtl:-scale-x-100" />
          </Link>
        </div>
      ) : null}
      {error ? (
        <div className="mx-auto mt-6 w-full max-w-xl">
          <ErrorNotice error={error} onRetry={() => submit(finished?.turn.query)} />
        </div>
      ) : null}
    </div>
  );
}
