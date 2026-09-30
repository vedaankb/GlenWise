// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 Ved Buddaraju

import { useEffect, useMemo, useRef, useState } from "react";
import type { ComposerHandle } from "@/components/Composer";
import { preloadAnswerRenderer } from "@/components/Turn";
import { Gate, Layout, ShortcutsDialog, Toaster } from "@/components/Shell";
import { Spinner } from "@/components/ui";
import { useT } from "@/i18n";
import { useShortcuts } from "@/lib/shortcuts";
import { DiagnosticsPage } from "@/pages/Diagnostics";
import { HomePage } from "@/pages/Home";
import { PrivatePage } from "@/pages/Private";
import { SettingsPage } from "@/pages/Settings";
import { SetupPage } from "@/pages/Setup";
import { ThreadPage } from "@/pages/Thread";
import { Link, navigate, useRoute } from "@/router";
import { useApp } from "@/state/app";
import { usePrefs } from "@/state/prefs";
import { clearPrivateMode } from "@/state/private";

const MODES = ["quick", "pro", "deep"] as const;

function NotFound() {
  const t = useT();
  return (
    <div className="mx-auto flex min-h-[70dvh] max-w-md flex-col items-center justify-center gap-3 px-5 text-center">
      <h1 className="m-0 text-2xl font-semibold tracking-tight">{t("notfound.title")}</h1>
      <p className="m-0 text-muted">{t("notfound.body")}</p>
      <Link to="/" className="btn btn-primary mt-2">
        {t("thread.missing.cta")}
      </Link>
    </div>
  );
}

export function App() {
  const t = useT();
  const route = useRoute();
  const { settings, gate } = useApp();
  const [, setPrefs] = usePrefs();
  const composerRef = useRef<ComposerHandle>(null);
  const [help, setHelp] = useState(false);

  useEffect(() => {
    const idle = window.requestIdleCallback ?? ((cb: () => void) => window.setTimeout(cb, 600));
    idle(preloadAnswerRenderer);
  }, []);

  // First run: guide to setup once, unless the user chose to skip it.
  useEffect(() => {
    if (
      settings &&
      !settings.configured &&
      route.name === "home" &&
      !route.q &&
      !sessionStorage.getItem("gleanwise.setup.skipped")
    )
      navigate("/setup", { replace: true });
  }, [settings, route]);

  useEffect(() => {
    if (route.name === "settings" || route.name === "diagnostics")
      document.title = `${t(`nav.${route.name}`)} · ${t("app.name")}`;
    else if (route.name !== "thread") document.title = t("app.name");
  }, [route.name, t]);

  const shortcuts = useMemo(
    () => ({
      newThread: () => {
        clearPrivateMode();
        navigate("/");
        setTimeout(() => composerRef.current?.focus(), 30);
      },
      focusSearch: () => composerRef.current?.focus(),
      setMode: (i: 0 | 1 | 2) => setPrefs({ mode: MODES[i] }),
      help: () => setHelp(true),
    }),
    [setPrefs],
  );
  useShortcuts(shortcuts);

  if (gate) return <Gate />;
  if (!settings)
    return (
      <div className="grid min-h-dvh place-items-center text-muted" role="status">
        <Spinner className="size-5" />
        <span className="sr-only">{t("common.loading")}</span>
      </div>
    );

  let page;
  switch (route.name) {
    case "setup":
      return (
        <>
          <SetupPage />
          <Toaster />
        </>
      );
    case "home":
      page = <HomePage composerRef={composerRef} />;
      break;
    case "private":
      page = <PrivatePage composerRef={composerRef} />;
      break;
    case "thread":
      page = <ThreadPage key={route.id} id={route.id} composerRef={composerRef} />;
      break;
    case "settings":
      page = <SettingsPage />;
      break;
    case "diagnostics":
      page = <DiagnosticsPage />;
      break;
    default:
      page = <NotFound />;
  }
  const pageKey = route.name === "thread" ? `thread-${route.id}` : route.name;
  return (
    <>
      <Layout>
        <div key={pageKey} className="page-in">
          {page}
        </div>
      </Layout>
      <ShortcutsDialog open={help} onOpenChange={setHelp} />
      <Toaster />
    </>
  );
}
