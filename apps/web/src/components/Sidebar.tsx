// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 Ved Buddaraju

import * as DropdownMenu from "@radix-ui/react-dropdown-menu";
import type { ThreadSummary } from "@gleanwise/react";
import {
  Activity,
  Lock,
  ShieldCheck,
  MoreHorizontal,
  Pencil,
  Pin,
  PinOff,
  Plus,
  Search,
  Settings,
  Trash2,
  X,
} from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { useI18n, type Key } from "@/i18n";
import { cn } from "@/lib/cn";
import { groupThreads } from "@/lib/format";
import { Link, navigate, useRoute } from "@/router";
import { useApp } from "@/state/app";
import { clearPrivateMode } from "@/state/private";
import { ConfirmDialog, IconButton, StatusDot } from "./ui";

const GROUP_LABEL: Record<string, Key> = {
  pinned: "sidebar.pinned",
  today: "sidebar.today",
  yesterday: "sidebar.yesterday",
  week: "sidebar.week",
  earlier: "sidebar.earlier",
};

function ThreadRow({ thread, active, onNavigate }: { thread: ThreadSummary; active: boolean; onNavigate(): void }) {
  const { t } = useI18n();
  const { patchThread, removeThread } = useApp();
  const [editing, setEditing] = useState(false);
  const [title, setTitle] = useState(thread.title);
  const [confirm, setConfirm] = useState(false);
  const input = useRef<HTMLInputElement>(null);
  useEffect(() => {
    if (editing) input.current?.select();
  }, [editing]);
  const commit = () => {
    setEditing(false);
    const next = title.trim();
    if (next && next !== thread.title) void patchThread(thread.id, { title: next });
    else setTitle(thread.title);
  };
  return (
    <li className="group/row relative">
      {editing ? (
        <input
          ref={input}
          value={title}
          onChange={(e) => setTitle(e.target.value)}
          onBlur={commit}
          onKeyDown={(e) => {
            if (e.key === "Enter") commit();
            if (e.key === "Escape") {
              setTitle(thread.title);
              setEditing(false);
            }
          }}
          aria-label={t("thread.rename")}
          className="field !min-h-9 !py-1.5 text-sm"
          maxLength={200}
        />
      ) : (
        <>
          <Link
            to={`/c/${thread.id}`}
            onClick={onNavigate}
            aria-current={active ? "page" : undefined}
            className={cn(
              "flex min-h-9 items-center gap-2 rounded-[10px] py-1.5 ps-3 pe-9 text-sm transition-colors",
              active ? "nav-active font-medium text-fg" : "text-muted hover:bg-surface-2 hover:text-fg",
            )}
          >
            {thread.pinned ? <Pin className="size-3 shrink-0 text-subtle" aria-label={t("sidebar.pinned")} /> : null}
            <span className="truncate">{thread.title || t("thread.untitled")}</span>
          </Link>
          <DropdownMenu.Root>
            <DropdownMenu.Trigger asChild>
              <button
                type="button"
                aria-label={t("thread.actions", { title: thread.title })}
                className="btn btn-ghost btn-sm btn-icon absolute end-1 top-1/2 -translate-y-1/2 opacity-0 transition-opacity focus-visible:opacity-100 group-hover/row:opacity-100 data-[state=open]:opacity-100 [@media(hover:none)]:opacity-100"
              >
                <MoreHorizontal className="size-4" />
              </button>
            </DropdownMenu.Trigger>
            <DropdownMenu.Portal>
              <DropdownMenu.Content className="menu" align="end" sideOffset={4}>
                <DropdownMenu.Item className="menu-item" onSelect={() => setEditing(true)}>
                  <Pencil className="size-4 text-muted" />
                  {t("thread.rename")}
                </DropdownMenu.Item>
                <DropdownMenu.Item
                  className="menu-item"
                  onSelect={() => void patchThread(thread.id, { pinned: !thread.pinned })}
                >
                  {thread.pinned ? <PinOff className="size-4 text-muted" /> : <Pin className="size-4 text-muted" />}
                  {thread.pinned ? t("thread.unpin") : t("thread.pin")}
                </DropdownMenu.Item>
                <DropdownMenu.Separator className="menu-sep" />
                <DropdownMenu.Item className="menu-item" data-danger="" onSelect={() => setConfirm(true)}>
                  <Trash2 className="size-4" />
                  {t("thread.delete")}
                </DropdownMenu.Item>
              </DropdownMenu.Content>
            </DropdownMenu.Portal>
          </DropdownMenu.Root>
        </>
      )}
      <ConfirmDialog
        open={confirm}
        onOpenChange={setConfirm}
        danger
        title={t("thread.delete.title")}
        body={t("thread.delete.body", { title: thread.title })}
        confirmLabel={t("thread.delete")}
        onConfirm={() => {
          void removeThread(thread.id);
          if (active) navigate("/", { replace: true });
        }}
      />
    </li>
  );
}

export function Sidebar({ onNavigate, onClose }: { onNavigate(): void; onClose?(): void }) {
  const { t } = useI18n();
  const { threads, threadsLoaded, settings, health, client } = useApp();
  const route = useRoute();
  const [query, setQuery] = useState("");
  const [hits, setHits] = useState<ThreadSummary[] | null>(null);

  useEffect(() => {
    const q = query.trim();
    if (!q) return setHits(null);
    const ctl = new AbortController();
    const id = window.setTimeout(() => {
      client.listThreads({ q, limit: 100 }).then(
        (r) => !ctl.signal.aborted && setHits(r),
        () => !ctl.signal.aborted && setHits([]),
      );
    }, 220);
    return () => {
      ctl.abort();
      window.clearTimeout(id);
    };
  }, [query, client]);

  const shown = hits ?? threads;
  const groups = useMemo(() => groupThreads(shown), [shown]);
  const activeId = route.name === "thread" ? route.id : null;

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="flex items-center justify-between px-4 pt-4 pb-2">
        <Link
          to="/"
          onClick={onNavigate}
          className="wordmark rounded-md text-[20px]"
          aria-label={t("app.name")}
        >
          {t("app.name")}
        </Link>
        {onClose ? (
          <IconButton label={t("common.close")} onClick={onClose}>
            <X className="size-4" />
          </IconButton>
        ) : null}
      </div>

      <div className="grid gap-2 px-3 pb-2">
        <Link
          to="/"
          onClick={() => {
            clearPrivateMode();
            onNavigate();
          }}
          className="btn btn-secondary w-full justify-between !px-3"
        >
          <span className="inline-flex items-center gap-2">
            <Plus className="size-4" />
            {t("sidebar.new")}
          </span>
          <kbd className="kbd" aria-hidden>
            ⌘K
          </kbd>
        </Link>
        <Link
          to="/private"
          onClick={onNavigate}
          className="btn btn-ghost w-full justify-start !px-3"
          aria-current={route.name === "private" ? "page" : undefined}
        >
          <Lock className="size-4" />
          {t("sidebar.private")}
        </Link>
      </div>

      <div className="relative px-3 pb-2">
        <Search className="pointer-events-none absolute start-6 top-1/2 size-4 -translate-y-[60%] text-subtle" />
        <input
          type="search"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder={t("sidebar.search")}
          aria-label={t("sidebar.search")}
          className="field !ps-9 !min-h-9 !rounded-[10px] text-sm"
        />
      </div>

      <nav aria-label={t("sidebar.history")} className="min-h-0 flex-1 overflow-y-auto px-3 pb-3">
        {!threadsLoaded ? (
          <div className="space-y-2 pt-2" aria-hidden>
            {[70, 55, 82, 48].map((w) => (
              <div key={w} className="skeleton h-8" style={{ inlineSize: `${w}%` }} />
            ))}
          </div>
        ) : groups.length === 0 ? (
          <p className="px-3 pt-4 text-sm text-muted">
            {query.trim()
              ? t("sidebar.noMatches")
              : t("sidebar.empty", { days: settings?.thread_retention_days ?? 28 })}
          </p>
        ) : (
          groups.map(({ group, items }) => (
            <section key={group} className="mt-3 first:mt-1" aria-label={t(GROUP_LABEL[group])}>
              <h2 className="px-3 pb-1 text-xs font-semibold tracking-wide text-muted">{t(GROUP_LABEL[group])}</h2>
              <ul className="space-y-0.5">
                {items.map((th) => (
                  <ThreadRow key={th.id} thread={th} active={th.id === activeId} onNavigate={onNavigate} />
                ))}
              </ul>
            </section>
          ))
        )}
      </nav>

      {settings?.strict_local ? (
        <Link
          to="/settings?section=privacy"
          onClick={onNavigate}
          className={cn(
            "mx-3 mb-2 inline-flex items-center gap-1.5 self-start rounded-full border px-2.5 py-1 text-[12px] font-medium",
            settings.llm_local ? "border-border-strong bg-surface-2 text-fg" : "border-warn/50 bg-warn-soft text-warn",
          )}
          title={settings.llm_local ? undefined : t("settings.strictLocal.remote")}
        >
          <ShieldCheck className="size-3.5" aria-hidden />
          {settings.llm_local ? t("sidebar.strictLocal") : t("sidebar.strictLocal.blocked")}
        </Link>
      ) : null}
      <div className="flex items-center justify-between gap-1 border-t border-border p-2">
        <Link
          to="/settings"
          onClick={onNavigate}
          aria-current={route.name === "settings" ? "page" : undefined}
          className={cn("btn btn-ghost btn-sm gap-2", route.name === "settings" && "bg-surface-2 !text-fg")}
        >
          <Settings className="size-4" />
          {t("nav.settings")}
        </Link>
        <Link
          to="/diagnostics"
          onClick={onNavigate}
          aria-current={route.name === "diagnostics" ? "page" : undefined}
          className={cn("btn btn-ghost btn-sm gap-2", route.name === "diagnostics" && "bg-surface-2 !text-fg")}
        >
          <Activity className="size-4" />
          {t("nav.diagnostics")}
          <StatusDot ok={health?.ok} pending={!health} />
          <span className="sr-only">{health ? (health.ok ? t("diag.ok") : t("diag.attention")) : ""}</span>
        </Link>
      </div>
    </div>
  );
}
