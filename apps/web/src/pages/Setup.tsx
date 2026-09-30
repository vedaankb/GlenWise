// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 Ved Buddaraju

import type { SetupTestResult } from "@gleanwise/react";
import { ArrowRight, Check, PartyPopper } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { LlmFields, TestButton, TestResults, providerOf, type LlmDraft, type Provider } from "@/components/Connection";
import { Button, FieldRow } from "@/components/ui";
import { useT } from "@/i18n";
import { cn } from "@/lib/cn";
import { Link, navigate } from "@/router";
import { useApp } from "@/state/app";

/** First-run: connect a model (tested for real before anything is saved), check search and embeddings, done. */
export function SetupPage() {
  const t = useT();
  const { client, settings, refreshSettings, refreshHealth, toast } = useApp();
  const [step, setStep] = useState(0);
  const [draft, setDraft] = useState<LlmDraft>({ llm_model: "", llm_api_key: "", llm_api_base: "" });
  const [provider, setProvider] = useState<Provider>(() => providerOf("", ""));
  const [results, setResults] = useState<SetupTestResult | null>(null);
  const [running, setRunning] = useState(false);
  const [searxng, setSearxng] = useState("");
  const locked = settings?.env_locked ?? [];

  useEffect(() => {
    if (!settings) return;
    setDraft((d) => ({
      llm_model: d.llm_model || settings.llm_model,
      llm_api_key: d.llm_api_key,
      llm_api_base: d.llm_api_base || settings.llm_api_base,
    }));
    setProvider((p) => (settings.llm_model ? providerOf(settings.llm_model, settings.llm_api_base) : p));
    setSearxng(settings.searxng_url);
  }, [settings?.llm_model, settings?.llm_api_base, settings?.searxng_url]); // eslint-disable-line react-hooks/exhaustive-deps

  const patch = (p: Partial<LlmDraft>) => setDraft((d) => ({ ...d, ...p }));
  const canTest =
    draft.llm_model.trim().length > 3 &&
    (provider.needsKey ? !!draft.llm_api_key || !!settings?.llm_api_key_set : true);
  const step1Steps = useMemo(() => [t("setup.step.model"), t("setup.step.check"), t("setup.step.done")], [t]);

  const runTest = async (trial: Parameters<typeof client.testSetup>[0]) => {
    setRunning(true);
    try {
      const r = await client.testSetup(trial);
      setResults(r);
      return r;
    } catch (e) {
      toast({ title: t("test.failed"), body: e instanceof Error ? e.message : undefined, tone: "error" });
      return null;
    } finally {
      setRunning(false);
    }
  };

  const testModel = async () => {
    const r = await runTest({
      llm_model: draft.llm_model,
      llm_api_key: draft.llm_api_key || undefined,
      llm_api_base: draft.llm_api_base || undefined,
    });
    if (r?.llm.ok) {
      try {
        await client.updateSettings({
          llm_model: draft.llm_model,
          ...(draft.llm_api_key ? { llm_api_key: draft.llm_api_key } : {}),
          llm_api_base: draft.llm_api_base,
        });
        await refreshSettings();
        setStep(1);
        void runTest({});
      } catch (e) {
        toast({ title: t("settings.saveFailed"), body: e instanceof Error ? e.message : undefined, tone: "error" });
      }
    }
  };

  const finish = async () => {
    await refreshSettings();
    await refreshHealth();
    setStep(2);
  };

  return (
    <main
      id="main"
      tabIndex={-1}
      className="mx-auto flex min-h-dvh w-full max-w-[34rem] outline-none flex-col justify-center px-5 py-10"
    >
      <ol className="mb-8 flex items-center gap-2" aria-label={t("setup.progress")}>
        {step1Steps.map((label, i) => (
          <li key={label} aria-current={i === step ? "step" : undefined} className="flex flex-1 items-center gap-2">
            <span
              className={cn(
                "grid size-6 shrink-0 place-items-center rounded-full text-xs font-semibold tabular",
                i < step ? "bg-accent text-accent-fg" : i === step ? "bg-fg text-bg" : "bg-surface-3 text-muted",
              )}
            >
              {i < step ? <Check className="size-3.5" strokeWidth={3} /> : i + 1}
            </span>
            <span className={cn("hidden text-[13px] font-medium sm:inline", i === step ? "text-fg" : "text-muted")}>
              {label}
            </span>
            {i < step1Steps.length - 1 ? (
              <span className={cn("h-px flex-1", i < step ? "bg-accent" : "bg-border")} aria-hidden />
            ) : null}
          </li>
        ))}
      </ol>

      {step === 0 ? (
        <section className="rise" aria-labelledby="setup-h">
          <h1 id="setup-h" className="m-0 text-[28px] font-semibold tracking-[-0.025em]">
            {t("setup.model.title")}
          </h1>
          <p className="mt-2 mb-6 text-muted">{t("setup.model.body")}</p>
          <LlmFields
            draft={draft}
            onChange={patch}
            settings={settings}
            provider={provider}
            onProvider={setProvider}
            lockedFields={locked}
          />
          {results && !running ? (
            <div className="mt-5">
              <TestResults
                results={{ ...results, search: { ...results.search }, embeddings: { ...results.embeddings } }}
                running={false}
              />
            </div>
          ) : null}
          <div className="mt-6 flex flex-wrap items-center gap-3">
            <TestButton onRun={() => void testModel()} running={running} disabled={!canTest} />
            <Link
              to="/"
              onClick={() => sessionStorage.setItem("gleanwise.setup.skipped", "1")}
              className="text-sm text-muted underline underline-offset-2"
            >
              {t("setup.skip")}
            </Link>
          </div>
          <p className="mt-3 text-[12.5px] text-muted">{t("setup.privacy")}</p>
        </section>
      ) : null}

      {step === 1 ? (
        <section className="rise" aria-labelledby="setup-h">
          <h1 id="setup-h" className="m-0 text-[28px] font-semibold tracking-[-0.025em]">
            {t("setup.check.title")}
          </h1>
          <p className="mt-2 mb-6 text-muted">{t("setup.check.body")}</p>
          <TestResults results={results} running={running} />
          {results && !results.search.ok ? (
            <div className="mt-5">
              <FieldRow
                label={t("settings.searxng")}
                htmlFor="setup-searx"
                hint={t("settings.searxng.hint")}
                locked={locked.includes("searxng_url") ? t("settings.locked") : undefined}
              >
                <input
                  id="setup-searx"
                  className="field font-mono !text-[13.5px]"
                  value={searxng}
                  onChange={(e) => setSearxng(e.target.value.trim())}
                  inputMode="url"
                  dir="ltr"
                  disabled={locked.includes("searxng_url")}
                  placeholder="http://127.0.0.1:8888"
                />
              </FieldRow>
              <Button
                className="mt-3"
                disabled={locked.includes("searxng_url")}
                onClick={async () => {
                  await client.updateSettings({ searxng_url: searxng }).catch((e: unknown) =>
                    toast({
                      title: t("settings.saveFailed"),
                      body: e instanceof Error ? e.message : undefined,
                      tone: "error",
                    }),
                  );
                  await refreshSettings();
                  void runTest({});
                }}
              >
                {t("setup.check.retry")}
              </Button>
            </div>
          ) : null}
          <div className="mt-6 flex items-center gap-3">
            <Button variant="primary" onClick={() => void finish()} disabled={running || !results?.llm.ok}>
              {results?.search.ok && results.embeddings.ok ? t("common.continue") : t("setup.check.anyway")}
              <ArrowRight className="size-4 rtl:-scale-x-100" />
            </Button>
            <Button variant="ghost" onClick={() => void runTest({})} disabled={running}>
              {t("diag.rerun")}
            </Button>
          </div>
        </section>
      ) : null}

      {step === 2 ? (
        <section className="rise text-center" aria-labelledby="setup-h">
          <span className="mx-auto mb-5 grid size-14 place-items-center rounded-full bg-accent/12 text-accent-text">
            <PartyPopper className="size-7" aria-hidden />
          </span>
          <h1 id="setup-h" className="m-0 text-[28px] font-semibold tracking-[-0.025em]">
            {t("setup.done.title")}
          </h1>
          <p className="mt-2 mb-6 text-muted">{t("setup.done.body")}</p>
          <Button variant="primary" onClick={() => navigate("/", { replace: true })}>
            {t("setup.done.cta")}
          </Button>
        </section>
      ) : null}
    </main>
  );
}
