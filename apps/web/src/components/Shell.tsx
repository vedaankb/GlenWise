// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 Ved Buddaraju

import * as Dialog from "@radix-ui/react-dialog";
import { Menu, Plus, WifiOff, KeyRound, X } from "lucide-react";
import { useState, type FormEvent, type ReactNode } from "react";
import { useT } from "@/i18n";
import { cn } from "@/lib/cn";
import { Link, navigate } from "@/router";
import { useApp } from "@/state/app";
import { Sidebar } from "./Sidebar";
import { Button, IconButton, Modal } from "./ui";

export function Toaster() {
  const { toasts, dismissToast } = useApp();
  const t = useT();
  return (
    <div
      className="pointer-events-none fixed inset-x-0 bottom-4 z-[80] flex flex-col items-center gap-2 px-4"
      role="region"
      aria-label={t("toast.region")}
    >
      {toasts.map((x) => (
        <div
          key={x.id}
          role={x.tone === "error" ? "alert" : "status"}
          className={cn(
            "pointer-events-auto rise flex w-full max-w-md items-start gap-3 rounded-[var(--radius-lg)] border bg-surface p-3.5 shadow-[var(--shadow-pop)]",
            x.tone === "error" ? "border-danger/40" : "border-border",
          )}
        >
          <div className="min-w-0 flex-1">
            <p className="m-0 text-sm font-semibold">{x.title}</p>
            {x.body ? <p className="m-0 mt-0.5 text-[13px] break-words text-muted">{x.body}</p> : null}
            {x.action ? (
              <button
                type="button"
                className="mt-1.5 text-[13px] font-semibold text-accent-text underline underline-offset-2"
                onClick={() => (x.action!.run(), dismissToast(x.id))}
              >
                {x.action.label}
              </button>
            ) : null}
          </div>
          <button
            type="button"
            className="btn btn-ghost btn-sm btn-icon -me-1 -mt-1"
            aria-label={t("common.dismiss")}
            onClick={() => dismissToast(x.id)}
          >
            <X className="size-4" />
          </button>
        </div>
      ))}
    </div>
  );
}

export function Layout({ children }: { children: ReactNode }) {
  const t = useT();
  const [drawer, setDrawer] = useState(false);
  return (
    <>
      <a href="#main" className="skip-link">
        {t("a11y.skip")}
      </a>
      <aside
        aria-label={t("sidebar.label")}
        className="fixed inset-y-0 start-0 z-30 hidden w-[var(--sidebar-w)] border-e border-border bg-surface/60 backdrop-blur-xl lg:block"
      >
        <Sidebar onNavigate={() => undefined} />
      </aside>

      <header className="sticky top-0 z-20 flex h-14 items-center gap-2 border-b border-border bg-bg/85 px-3 backdrop-blur-xl lg:hidden">
        <IconButton label={t("sidebar.open")} onClick={() => setDrawer(true)}>
          <Menu className="size-5" />
        </IconButton>
        <Link to="/" className="wordmark flex-1 text-[18px]">
          {t("app.name")}
        </Link>
        <Link to="/" aria-label={t("sidebar.new")} className="btn btn-ghost btn-icon">
          <Plus className="size-5" />
        </Link>
      </header>

      <Dialog.Root open={drawer} onOpenChange={setDrawer}>
        <Dialog.Portal>
          <Dialog.Overlay className="overlay" />
          <Dialog.Content className="drawer" aria-describedby={undefined}>
            <Dialog.Title className="sr-only">{t("sidebar.label")}</Dialog.Title>
            <Sidebar onNavigate={() => setDrawer(false)} onClose={() => setDrawer(false)} />
          </Dialog.Content>
        </Dialog.Portal>
      </Dialog.Root>

      <main id="main" tabIndex={-1} className="min-h-dvh outline-none lg:ps-[var(--sidebar-w)]">
        {children}
      </main>
    </>
  );
}

/** Full-screen state for "can't reach the server" and "needs an access token". */
export function Gate() {
  const t = useT();
  const { gate, retryConnect, setToken } = useApp();
  const [token, setTok] = useState("");
  if (!gate) return null;
  if (gate.kind === "auth") {
    const submit = (e: FormEvent) => {
      e.preventDefault();
      if (token.trim()) setToken(token.trim());
    };
    return (
      <div className="grid min-h-dvh place-items-center px-5">
        <form onSubmit={submit} className="card w-full max-w-sm p-6">
          <span className="mb-4 grid size-10 place-items-center rounded-full bg-accent/12 text-accent-text">
            <KeyRound className="size-5" aria-hidden />
          </span>
          <h1 className="m-0 text-xl font-semibold tracking-tight">{t("gate.auth.title")}</h1>
          <p className="mt-1 mb-4 text-sm text-muted">{t("gate.auth.body")}</p>
          <label htmlFor="token" className="mb-1.5 block text-[13.5px] font-semibold">
            {t("gate.auth.label")}
          </label>
          <input
            id="token"
            type="password"
            className="field font-mono"
            autoFocus
            autoComplete="off"
            value={token}
            onChange={(e) => setTok(e.target.value)}
            dir="ltr"
          />
          {gate.error.status === 401 && localStorage.getItem("gleanwise.token") ? (
            <p role="alert" className="mt-2 mb-0 text-[13px] text-danger">
              {t("gate.auth.wrong")}
            </p>
          ) : null}
          <Button variant="primary" className="mt-4 w-full" onClick={submit as never} disabled={!token.trim()}>
            {t("gate.auth.cta")}
          </Button>
        </form>
      </div>
    );
  }
  return (
    <div className="grid min-h-dvh place-items-center px-5">
      <div className="max-w-sm text-center" role="alert">
        <span className="mx-auto mb-4 grid size-12 place-items-center rounded-full bg-danger-soft text-danger">
          <WifiOff className="size-6" aria-hidden />
        </span>
        <h1 className="m-0 text-xl font-semibold tracking-tight">{t("gate.offline.title")}</h1>
        <p className="mt-1 mb-5 text-muted">{t("gate.offline.body", { origin: location.origin })}</p>
        <Button variant="primary" onClick={retryConnect}>
          {t("error.retry")}
        </Button>
      </div>
    </div>
  );
}

export function ShortcutsDialog({ open, onOpenChange }: { open: boolean; onOpenChange(o: boolean): void }) {
  const t = useT();
  const mod = /Mac|iPhone|iPad/.test(navigator.platform) ? "⌘" : "Ctrl";
  const rows: [string[], string][] = [
    [[mod, "K"], t("shortcut.new")],
    [["/"], t("shortcut.focus")],
    [["Alt", "1"], t("shortcut.quick")],
    [["Alt", "2"], t("shortcut.pro")],
    [["Alt", "3"], t("shortcut.deep")],
    [["Enter"], t("shortcut.send")],
    [["Shift", "Enter"], t("shortcut.newline")],
    [["?"], t("shortcut.help")],
  ];
  return (
    <Modal open={open} onOpenChange={onOpenChange} title={t("shortcut.title")}>
      <dl className="m-0 grid grid-cols-[1fr_auto] items-center gap-x-6 gap-y-2.5 text-sm">
        {rows.map(([keys, label]) => (
          <div key={label} className="contents">
            <dt className="text-muted">{label}</dt>
            <dd className="m-0 flex gap-1">
              {keys.map((k) => (
                <kbd key={k} className="kbd">
                  {k}
                </kbd>
              ))}
            </dd>
          </div>
        ))}
      </dl>
    </Modal>
  );
}

export { navigate };
