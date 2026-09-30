// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 Ved Buddaraju

import type { ErrorBody, WarningEvent } from "@gleanwise/react";
import { AlertTriangle, CircleAlert, RotateCcw, Settings, Stethoscope } from "lucide-react";
import { useT, type Key } from "@/i18n";
import { Link } from "@/router";
import { Button } from "./ui";

const WARN_KEYS: Record<string, Key> = {
  snippets_only: "warn.snippets_only",
  upgrade_failed: "warn.upgrade_failed",
  reranker_degraded: "warn.reranker_degraded",
};

/** Something worked but not fully. Shown inline, above the answer it affects. */
export function WarningNote({ warning }: { warning: WarningEvent }) {
  const t = useT();
  const key = WARN_KEYS[warning.code];
  return (
    <div
      role="note"
      className="flex items-start gap-2.5 rounded-[var(--radius)] border border-border bg-warn-soft px-3.5 py-2.5 text-[13.5px] text-warn"
    >
      <AlertTriangle className="mt-0.5 size-4 shrink-0" aria-hidden />
      <p className="m-0">{key ? t(key) : warning.message}</p>
    </div>
  );
}

/** A failed query: what happened, what to do, and a button that does it. */
export function ErrorNotice({
  error,
  onRetry,
  onEditQuery,
}: {
  error: ErrorBody;
  onRetry?(): void;
  onEditQuery?(): void;
}) {
  const t = useT();
  let action: React.ReactNode = null;
  if (error.action === "open_settings")
    action = (
      <Link to="/settings" className="btn btn-secondary btn-sm">
        <Settings className="size-4" />
        {t("error.openSettings")}
      </Link>
    );
  else if (error.action === "open_diagnostics")
    action = (
      <Link to="/diagnostics" className="btn btn-secondary btn-sm">
        <Stethoscope className="size-4" />
        {t("error.openDiagnostics")}
      </Link>
    );
  else if (error.action === "shorten_query" && onEditQuery)
    action = (
      <Button size="sm" onClick={onEditQuery}>
        {t("error.editQuery")}
      </Button>
    );
  const canRetry = onRetry && (error.retryable || error.action === "retry");
  return (
    <div role="alert" className="rounded-[var(--radius-lg)] border border-danger/30 bg-danger-soft p-4">
      <div className="flex items-start gap-3">
        <CircleAlert className="mt-0.5 size-5 shrink-0 text-danger" aria-hidden />
        <div className="min-w-0 flex-1">
          <p className="m-0 font-semibold text-fg">{error.message}</p>
          {error.hint ? <p className="mt-1 mb-0 text-sm text-muted">{error.hint}</p> : null}
          {action || canRetry ? (
            <div className="mt-3 flex flex-wrap gap-2">
              {action}
              {canRetry ? (
                <Button size="sm" onClick={onRetry}>
                  <RotateCcw className="size-3.5" />
                  {t("error.retry")}
                </Button>
              ) : null}
            </div>
          ) : null}
        </div>
      </div>
    </div>
  );
}
