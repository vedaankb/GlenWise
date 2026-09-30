// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 Ved Buddaraju

import type { EgressActivity, HealthResponse } from "@gleanwise/react";
import { Copy, RefreshCw, Trash2 } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { ComponentRow } from "@/components/Connection";
import { Button, StatusDot } from "@/components/ui";
import { useT } from "@/i18n";
import { useApp } from "@/state/app";

function formatBytes(n: number): string {
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / (1024 * 1024)).toFixed(1)} MB`;
}

export function DiagnosticsPage() {
  const t = useT();
  const { client, toast, refreshHealth } = useApp();
  const [report, setReport] = useState<HealthResponse | null>(null);
  const [egress, setEgress] = useState<EgressActivity | null>(null);
  const [running, setRunning] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const run = useCallback(async () => {
    setRunning(true);
    setError(null);
    try {
      const [h, e] = await Promise.all([client.diagnostics(), client.egressActivity()]);
      setReport(h);
      setEgress(e);
      void refreshHealth();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setRunning(false);
    }
  }, [client, refreshHealth]);
  useEffect(() => void run(), [run]);

  const copy = async () => {
    if (!report) return;
    const text = [
      `GleanWise ${report.version}`,
      ...report.components.map(
        (c) => `${c.ok ? "OK  " : "FAIL"} ${c.name}: ${c.detail}${c.hint ? ` — ${c.hint}` : ""}`,
      ),
    ].join("\n");
    try {
      await navigator.clipboard.writeText(text);
      toast({ title: t("diag.copied"), tone: "success" });
    } catch {
      toast({ title: t("toast.copyFailed"), tone: "error" });
    }
  };

  const clearLog = async () => {
    try {
      await client.clearEgress();
      setEgress(await client.egressActivity());
      toast({ title: t("diag.egress.cleared"), tone: "success" });
    } catch (e) {
      toast({ title: t("toast.actionFailed"), body: e instanceof Error ? e.message : undefined, tone: "error" });
    }
  };

  return (
    <div className="mx-auto w-full max-w-[44rem] px-5 py-10 sm:px-8">
      <div className="mb-6 flex flex-wrap items-center gap-3">
        <div className="min-w-0 flex-1">
          <h1 className="m-0 text-[28px] font-semibold tracking-[-0.025em]">{t("diag.title")}</h1>
          <p className="mt-1 mb-0 flex items-center gap-2 text-muted">
            {report ? (
              <>
                <StatusDot ok={report.ok} />
                {report.ok ? t("diag.allGood") : t("diag.needsAttention")} · v{report.version}
              </>
            ) : (
              t("diag.checking")
            )}
          </p>
        </div>
        <Button onClick={() => void copy()} disabled={!report}>
          <Copy className="size-4" />
          {t("diag.copy")}
        </Button>
        <Button variant="primary" onClick={() => void run()} busy={running}>
          <RefreshCw className="size-4" />
          {t("diag.rerun")}
        </Button>
      </div>
      {error ? (
        <p role="alert" className="rounded-[var(--radius)] border border-danger/30 bg-danger-soft p-4 text-danger">
          {error}
        </p>
      ) : null}
      <div className="card px-5" aria-busy={running}>
        {report ? (
          <ul className="m-0 list-none divide-y divide-border p-0">
            {report.components.map((c) => (
              <ComponentRow key={c.name} c={c} />
            ))}
          </ul>
        ) : (
          <div className="space-y-5 py-5" aria-hidden>
            {[0, 1, 2, 3].map((i) => (
              <div key={i} className="flex gap-3">
                <div className="skeleton size-6 rounded-full" />
                <div className="flex-1 space-y-2">
                  <div className="skeleton h-4 w-1/4" />
                  <div className="skeleton h-3 w-2/3" />
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      <section className="mt-10" aria-labelledby="egress-h">
        <div className="mb-3 flex flex-wrap items-end justify-between gap-3">
          <div>
            <h2 id="egress-h" className="m-0 text-[17px] font-semibold tracking-tight">
              {t("diag.egress.title")}
            </h2>
            <p className="mt-1 mb-0 text-[13.5px] text-muted">
              {t("diag.egress.desc")}
              {egress?.gateway ? (
                <>
                  {" "}
                  · {t("diag.egress.gateway")}: <span className="font-mono text-[12.5px]">{egress.gateway}</span>
                  {egress.gateway_status ? ` (${egress.gateway_status})` : ""}
                </>
              ) : null}
            </p>
          </div>
          <Button size="sm" onClick={() => void clearLog()} disabled={!egress?.entries?.length}>
            <Trash2 className="size-3.5" />
            {t("diag.egress.clear")}
          </Button>
        </div>
        <div className="card overflow-x-auto">
          {egress?.entries && egress.entries.length ? (
            <table className="w-full min-w-[32rem] border-collapse text-start text-[13px]">
              <thead>
                <tr className="border-b border-border text-muted">
                  <th className="px-4 py-2.5 font-medium">{t("diag.egress.time")}</th>
                  <th className="px-4 py-2.5 font-medium">{t("diag.egress.host")}</th>
                  <th className="px-4 py-2.5 font-medium">{t("diag.egress.purpose")}</th>
                  <th className="px-4 py-2.5 font-medium">{t("diag.egress.bytes")}</th>
                  <th className="px-4 py-2.5 font-medium">{t("diag.egress.status")}</th>
                </tr>
              </thead>
              <tbody>
                {egress.entries.map((e, i) => (
                  <tr key={`${e.ts}-${e.host}-${i}`} className="border-b border-border last:border-b-0">
                    <td className="px-4 py-2 tabular text-muted">{new Date(e.ts * 1000).toLocaleTimeString()}</td>
                    <td className="px-4 py-2 font-mono text-[12.5px]">
                      {e.host}:{e.port}
                    </td>
                    <td className="px-4 py-2">{e.purpose}</td>
                    <td className="px-4 py-2 tabular text-muted">
                      ↓{formatBytes(e.bytes_in)} · ↑{formatBytes(e.bytes_out)}
                    </td>
                    <td className="px-4 py-2">
                      <span className={e.status === "ok" || e.status === "connected" ? "text-success" : "text-danger"}>
                        {e.status}
                      </span>
                      {e.detail ? <span className="ms-1 text-muted">· {e.detail}</span> : null}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : (
            <p className="m-0 px-5 py-8 text-center text-sm text-muted">{t("diag.egress.empty")}</p>
          )}
        </div>
      </section>
    </div>
  );
}
