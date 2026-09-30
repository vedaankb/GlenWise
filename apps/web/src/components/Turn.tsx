// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 Ved Buddaraju

import * as DropdownMenu from "@radix-ui/react-dropdown-menu";
import { LabelsProvider, type UiLabels } from "@ui/labels";
import { SourceList } from "@ui/SourceList";
import type { AnswerState, Mode } from "@gleanwise/react";
import {
  Check,
  Copy,
  Download,
  FileText,
  Info,
  RefreshCw,
  Sparkles,
  ThumbsDown,
  ThumbsUp,
  BookOpenCheck,
  Search,
} from "lucide-react";
import { lazy, Suspense, useEffect, useMemo, useRef, useState } from "react";
import { useI18n, type Key } from "@/i18n";
import { cn } from "@/lib/cn";
import { answerToMarkdown, download, researchLogToMarkdown, slug } from "@/lib/format";
import { saveScroll } from "@/router";
import { useApp } from "@/state/app";
import { ErrorNotice, WarningNote } from "./Notices";
import { ResearchPanel } from "./Research";
import { IconButton, Spinner } from "./ui";

// Markdown, math and syntax highlighting are large; load them on first answer, not on first paint.
const AnswerMarkdown = lazy(() => import("@ui/AnswerMarkdown").then((m) => ({ default: m.AnswerMarkdown })));
export const preloadAnswerRenderer = () => void import("@ui/AnswerMarkdown");

export interface TurnData {
  id: string;
  query: string;
  mode: Mode;
  state: AnswerState;
  live: boolean;
  /** The assistant message this turn shows (regenerate replaces it). */
  messageId?: string | null;
}

const STEPS: { id: "searching" | "reading" | "writing"; label: Key; icon: typeof Search }[] = [
  { id: "searching", label: "step.searching", icon: Search },
  { id: "reading", label: "step.reading", icon: BookOpenCheck },
  { id: "writing", label: "step.writing", icon: FileText },
];

export function Steps({ state }: { state: AnswerState }) {
  const { t } = useI18n();
  const current = state.phase === "writing" ? 2 : state.phase === "reading" ? 1 : 0;
  const read = state.sources.filter((s) => s.state === "read" || s.state === "failed" || s.state === "skipped").length;
  return (
    <ol className="m-0 flex list-none flex-wrap items-center gap-2 p-0" aria-label={t("step.progress")}>
      {STEPS.map((s, i) => {
        const done = i < current;
        const active = i === current;
        return (
          <li
            key={s.id}
            aria-current={active ? "step" : undefined}
            className={cn(
              "flex items-center gap-1.5 rounded-full border px-3 py-1 text-[13px] font-medium transition-colors",
              active
                ? "border-accent/40 bg-accent/10 text-accent-text"
                : done
                  ? "border-transparent bg-surface-2 text-muted"
                  : "border-transparent text-subtle",
            )}
          >
            {done ? (
              <Check className="size-3.5" aria-hidden />
            ) : active ? (
              <Spinner className="size-3.5" />
            ) : (
              <s.icon className="size-3.5" aria-hidden />
            )}
            {t(s.label)}
            {active && s.id === "reading" && state.sources.length ? (
              <span className="tabular opacity-80">
                {read}/{state.sources.length}
              </span>
            ) : null}
          </li>
        );
      })}
    </ol>
  );
}

function Skeleton() {
  return (
    <div className="space-y-3 pt-1" aria-hidden>
      <div className="skeleton h-4 w-[92%]" />
      <div className="skeleton h-4 w-[97%]" />
      <div className="skeleton h-4 w-[64%]" />
    </div>
  );
}

function Actions({
  turn,
  onRegenerate,
  onFeedback,
  feedback,
  threadId,
}: {
  turn: TurnData;
  onRegenerate(mode: Mode): void;
  onFeedback(v: -1 | 0 | 1): void;
  feedback: -1 | 0 | 1;
  threadId?: string;
}) {
  const { t } = useI18n();
  const { client, toast } = useApp();
  const [copied, setCopied] = useState(false);
  const s = turn.state;
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(answerToMarkdown(turn.query, s, { sources: t("answer.sources") }));
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1800);
    } catch {
      toast({ title: t("toast.copyFailed"), tone: "error" });
    }
  };
  const exportThread = async (format: "md" | "pdf") => {
    if (!threadId) return;
    try {
      download(await client.exportThread(threadId, format), `${slug(turn.query)}.${format}`);
    } catch (e) {
      toast({ title: t("toast.exportFailed"), body: e instanceof Error ? e.message : undefined, tone: "error" });
    }
  };
  return (
    <div role="toolbar" aria-label={t("actions.label")} className="-ms-2 flex flex-wrap items-center gap-0.5">
      <IconButton label={copied ? t("actions.copied") : t("actions.copy")} onClick={() => void copy()} size="sm">
        {copied ? <Check className="size-4 text-success" /> : <Copy className="size-4" />}
      </IconButton>

      <DropdownMenu.Root>
        <DropdownMenu.Trigger asChild>
          <button type="button" aria-label={t("actions.regenerate")} className="btn btn-ghost btn-sm btn-icon">
            <RefreshCw className="size-4" />
          </button>
        </DropdownMenu.Trigger>
        <DropdownMenu.Portal>
          <DropdownMenu.Content className="menu" align="start" sideOffset={4}>
            <DropdownMenu.Label className="menu-label">{t("actions.rerun")}</DropdownMenu.Label>
            {(["quick", "pro", "deep"] as Mode[]).map((m) => (
              <DropdownMenu.Item key={m} className="menu-item" onSelect={() => onRegenerate(m)}>
                <span className="flex-1">{t(`mode.${m}` as Key)}</span>
                {m === turn.mode ? <span className="text-xs text-muted">{t("actions.sameMode")}</span> : null}
              </DropdownMenu.Item>
            ))}
          </DropdownMenu.Content>
        </DropdownMenu.Portal>
      </DropdownMenu.Root>

      <DropdownMenu.Root>
        <DropdownMenu.Trigger asChild>
          <button
            type="button"
            aria-label={t("actions.export")}
            className="btn btn-ghost btn-sm btn-icon"
            disabled={!threadId}
          >
            <Download className="size-4" />
          </button>
        </DropdownMenu.Trigger>
        <DropdownMenu.Portal>
          <DropdownMenu.Content className="menu" align="start" sideOffset={4}>
            <DropdownMenu.Label className="menu-label">{t("actions.exportThread")}</DropdownMenu.Label>
            <DropdownMenu.Item className="menu-item" onSelect={() => void exportThread("md")}>
              Markdown
            </DropdownMenu.Item>
            <DropdownMenu.Item className="menu-item" onSelect={() => void exportThread("pdf")}>
              PDF
            </DropdownMenu.Item>
            {turn.mode === "deep" ? (
              <>
                <DropdownMenu.Separator className="menu-sep" />
                <DropdownMenu.Item
                  className="menu-item"
                  onSelect={() =>
                    download(
                      new Blob([researchLogToMarkdown(turn.query, s)], { type: "text/markdown" }),
                      `${slug(turn.query)}-research-log.md`,
                    )
                  }
                >
                  {t("actions.researchLog")}
                </DropdownMenu.Item>
              </>
            ) : null}
          </DropdownMenu.Content>
        </DropdownMenu.Portal>
      </DropdownMenu.Root>

      <span className="mx-1 h-4 w-px bg-border" aria-hidden />
      {s.dataFlow ? (
        <DropdownMenu.Root>
          <DropdownMenu.Trigger asChild>
            <button type="button" aria-label={t("flow.label")} className="btn btn-ghost btn-sm btn-icon">
              <Info className="size-4" />
            </button>
          </DropdownMenu.Trigger>
          <DropdownMenu.Portal>
            <DropdownMenu.Content className="menu max-w-xs" align="start" sideOffset={4}>
              <DropdownMenu.Label className="menu-label">{t("flow.label")}</DropdownMenu.Label>
              <div className="grid gap-1.5 px-2.5 py-1.5 text-[13px] text-muted">
                <p className="m-0">
                  {t("flow.search")}: {s.dataFlow.search ? t("flow.yes") : t("flow.no")}
                </p>
                <p className="m-0">
                  {t("flow.pages")}: {s.dataFlow.pages_fetched}
                </p>
                <p className="m-0">
                  {t("flow.model")}: {s.dataFlow.model || "—"} (
                  {s.dataFlow.model_local ? t("flow.local") : t("flow.cloud")})
                </p>
                <p className="m-0">
                  {t("flow.redaction")}: {s.dataFlow.redaction ? t("flow.on") : t("flow.off")}
                </p>
                <p className="m-0">
                  {t("flow.proxy")}: {s.dataFlow.proxy ? t("flow.on") : t("flow.off")}
                  {s.dataFlow.socks5 ? ` · ${t("flow.socks5")}` : ""}
                </p>
                {s.dataFlow.strict_local ? <p className="m-0">{t("flow.strictLocal")}</p> : null}
                {s.dataFlow.private ? <p className="m-0">{t("flow.private")}</p> : null}
              </div>
            </DropdownMenu.Content>
          </DropdownMenu.Portal>
        </DropdownMenu.Root>
      ) : null}
      {!s.dataFlow?.private ? (
        <>
          <IconButton
            label={t("actions.good")}
            size="sm"
            aria-pressed={feedback === 1}
            onClick={() => onFeedback(feedback === 1 ? 0 : 1)}
          >
            <ThumbsUp className={cn("size-4", feedback === 1 && "fill-current text-accent-text")} />
          </IconButton>
          <IconButton
            label={t("actions.bad")}
            size="sm"
            aria-pressed={feedback === -1}
            onClick={() => onFeedback(feedback === -1 ? 0 : -1)}
          >
            <ThumbsDown className={cn("size-4", feedback === -1 && "fill-current text-accent-text")} />
          </IconButton>
        </>
      ) : null}
    </div>
  );
}

export function Turn({
  turn,
  threadId,
  onFollowUp,
  onRegenerate,
  onRetry,
  onEditQuery,
}: {
  turn: TurnData;
  threadId?: string;
  onFollowUp(q: string): void;
  onRegenerate(turn: TurnData, mode: Mode): void;
  onRetry(turn: TurnData): void;
  onEditQuery(turn: TurnData): void;
}) {
  const { t, locale } = useI18n();
  const { client, toast } = useApp();
  const s = turn.state;
  const resolveAsset = useMemo(() => (p: string) => client.asset(p) ?? p, [client]);
  const resolveImage = useMemo(() => (src: string) => client.imageUrl(src), [client]);
  const labels = useMemo<UiLabels>(
    () => ({
      copy: t("code.copy"),
      copied: t("code.copied"),
      source: (n) => t("cite.source", { n }),
      openSource: t("cite.open"),
      usedInAnswer: t("source.used"),
      reading: t("source.reading"),
      failed: t("source.failed"),
      skipped: t("source.skipped"),
      imageBlocked: t("answer.imageBlocked"),
    }),
    [t],
  );

  // Keep the quick draft on screen (dimmed) until the refined answer starts, so upgrading never flashes blank.
  const draftText = useRef("");
  if (s.draft && s.answer) draftText.current = s.answer;
  const showingDraft = s.draft || (s.refining && !s.answer);
  const display = s.refining && !s.answer ? draftText.current : s.answer;
  const wasRefined = useRef(false);
  if (s.refining) wasRefined.current = true;

  const fbKey = `gleanwise.fb.${s.queryId ?? turn.id}`;
  const [feedback, setFeedback] = useState<-1 | 0 | 1>(() => (Number(localStorage.getItem(fbKey)) || 0) as -1 | 0 | 1);
  const sendFeedback = (v: -1 | 0 | 1) => {
    setFeedback(v);
    localStorage.setItem(fbKey, String(v));
    if (s.queryId)
      client.feedback(s.queryId, v).catch(() => toast({ title: t("toast.feedbackFailed"), tone: "error" }));
  };

  const isDeep = turn.mode === "deep";
  const running = turn.live && !["done", "error", "cancelled"].includes(s.phase);
  const hasAnswer = display.trim().length > 0;
  const done = s.phase === "done" || s.phase === "cancelled" || !turn.live;
  const showSourcesSkeleton = running && s.sources.length === 0;
  const showSources = s.sources.filter((x) => x.state !== "failed").length > 0;

  // The answer streams in place; make sure a newly started turn is in view.
  const ref = useRef<HTMLElement>(null);
  useEffect(() => {
    if (turn.live && s.phase === "connecting")
      ref.current?.scrollIntoView({
        block: "start",
        behavior: matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth",
      });
  }, [turn.live, s.phase]);

  return (
    <LabelsProvider value={labels}>
      <article
        ref={ref}
        aria-labelledby={`q-${turn.id}`}
        className="scroll-mt-20 border-b border-border pb-10 last:border-b-0"
        data-phase={s.phase}
      >
        <h2
          id={`q-${turn.id}`}
          className="h-display m-0 mb-6 text-[28px] leading-[1.2] tracking-[-0.02em] text-balance sm:text-[34px]"
        >
          {turn.query}
        </h2>
        <div className="grid gap-x-10 gap-y-6 lg:grid-cols-[minmax(0,1fr)_16.5rem]">
          <div className="min-w-0 space-y-5">
            {running && !(isDeep && !hasAnswer) ? <Steps state={s} /> : null}
            {isDeep && (running || s.visits.length > 0 || s.reasoning) ? (
              <ResearchPanel state={s} live={running && !hasAnswer} resolveAsset={resolveAsset} />
            ) : null}

            {s.warnings.map((w, i) => (
              <WarningNote key={`${w.code}-${i}`} warning={w} />
            ))}

            {hasAnswer ? (
              <div
                className={cn(running && "answer-streaming", showingDraft && "opacity-70 transition-opacity")}
                aria-busy={running || undefined}
              >
                {showingDraft ? (
                  <p className="mb-3 flex items-center gap-2 text-[13px] font-medium text-muted">
                    <Spinner className="size-3.5" />
                    {t("answer.draft")}
                  </p>
                ) : null}
                <Suspense fallback={<div className="gw-answer whitespace-pre-wrap">{display}</div>}>
                  <AnswerMarkdown
                    text={display}
                    sources={s.sources}
                    citations={s.citations}
                    resolveImage={resolveImage}
                    resolveAsset={resolveAsset}
                    onOpenSource={() => saveScroll()}
                  />
                </Suspense>
              </div>
            ) : running && !isDeep ? (
              <Skeleton />
            ) : null}

            {done && wasRefined.current && s.phase === "done" && hasAnswer ? (
              <p className="m-0 flex items-center gap-1.5 text-[13px] text-muted fade-out-later" data-testid="upgraded">
                <Sparkles className="size-3.5 text-accent-text" aria-hidden />
                {t("answer.upgraded")}
              </p>
            ) : null}

            {s.phase === "cancelled" ? (
              <p className="m-0 text-sm text-muted">{hasAnswer ? t("answer.stoppedPartial") : t("answer.stopped")}</p>
            ) : null}
            {s.error ? (
              <ErrorNotice error={s.error} onRetry={() => onRetry(turn)} onEditQuery={() => onEditQuery(turn)} />
            ) : null}

            {!running && !s.error && hasAnswer ? (
              <>
                <Actions
                  turn={turn}
                  threadId={s.dataFlow?.private ? undefined : threadId}
                  onRegenerate={(m) => onRegenerate(turn, m)}
                  feedback={feedback}
                  onFeedback={sendFeedback}
                />
                {s.followUps.length ? (
                  <div role="group" aria-labelledby={`fu-${turn.id}`} className="pt-1">
                    <h3 id={`fu-${turn.id}`} className="mb-2 text-xs font-semibold tracking-wide text-muted">
                      {t("answer.followUps")}
                    </h3>
                    <ul className="m-0 flex list-none flex-col items-start gap-2 p-0">
                      {s.followUps.map((q) => (
                        <li key={q}>
                          <button
                            type="button"
                            onClick={() => onFollowUp(q)}
                            className="rounded-2xl border border-border bg-surface px-3.5 py-2 text-start text-[14px] leading-snug transition-colors hover:border-border-strong hover:bg-surface-2"
                          >
                            {q}
                          </button>
                        </li>
                      ))}
                    </ul>
                  </div>
                ) : null}
              </>
            ) : null}
          </div>

          <div role="group" aria-labelledby={`src-${turn.id}`} className="min-w-0">
            <div className="sources-panel lg:sticky lg:top-6">
              <h3
                id={`src-${turn.id}`}
                className="sources-heading mb-1 flex items-center gap-2 px-2 font-semibold text-muted"
              >
                {t("answer.sources")}
                {s.sources.length ? (
                  <span className="tabular rounded-full bg-surface-3 px-1.5 py-px text-[10px]">{s.sources.length}</span>
                ) : null}
              </h3>
              {showSourcesSkeleton ? (
                <div className="space-y-4 p-2" aria-hidden>
                  {[0, 1, 2].map((i) => (
                    <div key={i} className="space-y-2">
                      <div className="skeleton h-3 w-1/3" />
                      <div className="skeleton h-4 w-4/5" />
                      <div className="skeleton h-3 w-full" />
                    </div>
                  ))}
                </div>
              ) : showSources ? (
                <div className="lg:max-h-[calc(100dvh-10rem)] lg:overflow-y-auto">
                  <SourceList
                    sources={s.sources}
                    locale={locale}
                    resolveAsset={resolveAsset}
                    onOpen={() => saveScroll()}
                  />
                </div>
              ) : done && !s.error ? (
                <p className="m-0 px-0.5 text-sm text-muted">{t("answer.noSources")}</p>
              ) : null}
            </div>
          </div>
        </div>
      </article>
    </LabelsProvider>
  );
}
