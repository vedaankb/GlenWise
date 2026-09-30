// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 Ved Buddaraju

import type { SetupTestResult, SettingsUpdate } from "@gleanwise/react";
import { Check } from "lucide-react";
import { useEffect, useMemo, useState, type ReactNode } from "react";
import { LlmFields, TestButton, TestResults, providerOf, type Provider } from "@/components/Connection";
import { Button, ConfirmDialog, FieldRow, Modal, Segmented, Toggle } from "@/components/ui";
import { LOCALES, useI18n } from "@/i18n";
import { cn } from "@/lib/cn";
import { useApp } from "@/state/app";
import { ACCENTS, usePrefs, type Accent, type Theme } from "@/state/prefs";

const SWATCH: Record<Accent, string> = {
  indigo: "#4f46e5",
  teal: "#0f766e",
  rose: "#be123c",
  amber: "#b45309",
  green: "#15803d",
  graphite: "#374151",
};

function Section({
  id,
  title,
  description,
  children,
}: {
  id: string;
  title: string;
  description?: string;
  children: ReactNode;
}) {
  return (
    <section id={id} aria-labelledby={`${id}-h`} className="scroll-mt-6">
      <h2 id={`${id}-h`} className="m-0 text-[17px] font-semibold tracking-tight">
        {title}
      </h2>
      {description ? <p className="mt-1 mb-0 text-[13.5px] text-muted">{description}</p> : null}
      <div className="card mt-4 grid gap-5 p-5">{children}</div>
    </section>
  );
}

export function SettingsPage() {
  const { t, preference, setPreference } = useI18n();
  const { client, settings, refreshSettings, refreshHealth, toast } = useApp();
  const [prefs, setPrefs] = usePrefs();
  const [draft, setDraft] = useState<SettingsUpdate>({});
  const [provider, setProvider] = useState<Provider | null>(null);
  const [saving, setSaving] = useState(false);
  const [testing, setTesting] = useState(false);
  const [results, setResults] = useState<SetupTestResult | null>(null);
  const [removeKey, setRemoveKey] = useState(false);
  const [confirm, setConfirm] = useState<"cache" | "wipe" | "metrics" | "webhooks" | null>(null);
  const [wipeText, setWipeText] = useState("");

  useEffect(() => {
    if (settings && !provider) setProvider(providerOf(settings.llm_model, settings.llm_api_base));
  }, [settings, provider]);

  const locked = settings?.env_locked ?? [];
  const value = <K extends keyof SettingsUpdate>(k: K, fallback: string | number): string | number =>
    (draft[k] ??
      (settings ? (settings as unknown as Record<string, string | number>)[k as string] : undefined) ??
      fallback) as string | number;
  const set = (patch: SettingsUpdate) => setDraft((d) => ({ ...d, ...patch }));
  const dirtyKeys = useMemo(() => {
    const changed = Object.entries(draft).filter(([k, v]) => {
      if (!settings) return false;
      if (k === "llm_api_key") return v !== undefined && v !== "";
      return (settings as unknown as Record<string, unknown>)[k] !== v;
    });
    if (removeKey && !draft.llm_api_key) changed.push(["llm_api_key", ""]);
    return changed;
  }, [draft, settings, removeKey]);
  const dirty = dirtyKeys.length > 0;

  useEffect(() => {
    const warn = (e: BeforeUnloadEvent) => {
      if (dirty) e.preventDefault();
    };
    addEventListener("beforeunload", warn);
    return () => removeEventListener("beforeunload", warn);
  }, [dirty]);

  if (!settings || !provider)
    return (
      <div className="mx-auto max-w-3xl px-5 py-10">
        <div className="skeleton h-8 w-40" />
      </div>
    );

  const save = async () => {
    setSaving(true);
    try {
      const patch = Object.fromEntries(dirtyKeys) as SettingsUpdate;
      await client.updateSettings(patch);
      await refreshSettings();
      void refreshHealth();
      setDraft({});
      setRemoveKey(false);
      toast({ title: t("settings.saved"), tone: "success" });
    } catch (e) {
      toast({ title: t("settings.saveFailed"), body: e instanceof Error ? e.message : undefined, tone: "error" });
    } finally {
      setSaving(false);
    }
  };

  const test = async () => {
    setTesting(true);
    try {
      setResults(
        await client.testSetup({
          llm_model: draft.llm_model ?? undefined,
          llm_api_key: draft.llm_api_key || undefined,
          llm_api_base: draft.llm_api_base ?? undefined,
          searxng_url: draft.searxng_url ?? undefined,
        }),
      );
    } catch (e) {
      toast({ title: t("test.failed"), body: e instanceof Error ? e.message : undefined, tone: "error" });
    } finally {
      setTesting(false);
    }
  };

  const nav = [
    ["model", t("settings.model")],
    ["search", t("settings.search")],
    ["embeddings", t("settings.embeddings")],
    ["privacy", t("settings.privacy")],
    ["data", t("settings.data")],
    ["appearance", t("settings.appearance")],
    ["advanced", t("settings.advanced")],
  ] as const;

  return (
    <div className="mx-auto w-full max-w-[60rem] px-5 pt-8 pb-32 sm:px-8 lg:pt-10">
      <h1 className="m-0 mb-1 text-[28px] font-semibold tracking-[-0.025em]">{t("settings.title")}</h1>
      <p className="mt-0 mb-8 text-muted">{t("settings.subtitle")}</p>

      <div className="grid gap-10 lg:grid-cols-[11rem_minmax(0,1fr)]">
        <nav aria-label={t("settings.sections")} className="hidden lg:block">
          <ul className="sticky top-8 m-0 grid list-none gap-0.5 p-0">
            {nav.map(([id, label]) => (
              <li key={id}>
                <a
                  href={`#${id}`}
                  className="block rounded-[10px] px-3 py-1.5 text-[13.5px] text-muted hover:bg-surface-2 hover:text-fg"
                >
                  {label}
                </a>
              </li>
            ))}
          </ul>
        </nav>

        <div className="grid gap-10">
          <Section id="model" title={t("settings.model")} description={t("settings.model.desc")}>
            <LlmFields
              draft={{
                llm_model: String(value("llm_model", "")),
                llm_api_key: draft.llm_api_key ?? "",
                llm_api_base: String(value("llm_api_base", "")),
              }}
              onChange={(p) => set(p)}
              settings={settings}
              provider={provider}
              onProvider={setProvider}
              lockedFields={locked}
            />
            <div className="flex flex-wrap items-center gap-3">
              <TestButton
                onRun={() => void test()}
                running={testing}
                disabled={!settings.llm_model && !draft.llm_model}
              />
              {settings.llm_api_key_set && !locked.includes("llm_api_key") ? (
                <Button variant="ghost" size="sm" onClick={() => setRemoveKey((v) => !v)} aria-pressed={removeKey}>
                  {removeKey ? t("llm.key.keep") : t("llm.key.remove")}
                </Button>
              ) : null}
            </div>
            {results || testing ? <TestResults results={results} running={testing} /> : null}
          </Section>

          <Section id="search" title={t("settings.search")} description={t("settings.search.desc")}>
            <FieldRow
              label={t("settings.searxng")}
              htmlFor="s-searx"
              hint={t("settings.searxng.hint")}
              locked={locked.includes("searxng_url") ? t("settings.locked") : undefined}
            >
              <input
                id="s-searx"
                className="field font-mono !text-[13.5px]"
                value={String(value("searxng_url", ""))}
                onChange={(e) => set({ searxng_url: e.target.value.trim() })}
                disabled={locked.includes("searxng_url")}
                inputMode="url"
                dir="ltr"
              />
            </FieldRow>
          </Section>

          <Section id="embeddings" title={t("settings.embeddings")} description={t("settings.embeddings.desc")}>
            <FieldRow
              label={t("settings.embedder")}
              hint={t(`settings.embedder.${value("embedder", "local")}` as never)}
              locked={locked.includes("embedder") ? t("settings.locked") : undefined}
            >
              <Segmented
                label={t("settings.embedder")}
                value={String(value("embedder", "local"))}
                onChange={(v) => set({ embedder: v as "local" | "litellm" | "hash" })}
                options={[
                  { value: "local", label: t("settings.embedder.local.label") },
                  { value: "litellm", label: t("settings.embedder.litellm.label") },
                  { value: "hash", label: t("settings.embedder.hash.label") },
                ]}
              />
            </FieldRow>
            {value("embedder", "local") !== "hash" ? (
              <FieldRow
                label={t("settings.embedModel")}
                htmlFor="s-embed"
                hint={t("settings.embedModel.hint")}
                locked={locked.includes("embed_model") ? t("settings.locked") : undefined}
              >
                <input
                  id="s-embed"
                  className="field font-mono !text-[13.5px]"
                  value={String(value("embed_model", ""))}
                  onChange={(e) => set({ embed_model: e.target.value.trim() })}
                  disabled={locked.includes("embed_model")}
                  placeholder={t("settings.embedModel.placeholder")}
                  dir="ltr"
                  spellCheck={false}
                />
              </FieldRow>
            ) : null}
          </Section>

          <Section id="privacy" title={t("settings.privacy")} description={t("settings.privacy.desc")}>
            <FieldRow
              label={t("settings.strictLocal")}
              hint={t("settings.strictLocal.hint")}
              locked={locked.includes("strict_local") ? t("settings.locked") : undefined}
            >
              <Toggle
                id="s-strict"
                label={t("settings.strictLocal")}
                checked={draft.strict_local ?? settings.strict_local}
                onChange={(v) => set({ strict_local: v })}
              />
              {(draft.strict_local ?? settings.strict_local) && !settings.llm_local ? (
                <p role="alert" className="mt-2 mb-0 text-[13px] text-warn">
                  {t("settings.strictLocal.remote")}
                </p>
              ) : null}
            </FieldRow>
            <FieldRow
              label={t("settings.redactPii")}
              hint={t("settings.redactPii.hint")}
              locked={locked.includes("redact_pii") ? t("settings.locked") : undefined}
            >
              <Toggle
                id="s-redact"
                label={t("settings.redactPii")}
                checked={draft.redact_pii ?? settings.redact_pii}
                onChange={(v) => set({ redact_pii: v })}
              />
            </FieldRow>
            <FieldRow
              label={t("settings.egressGateway")}
              hint={t("settings.egressGateway.hint")}
              locked={locked.includes("egress_gateway") ? t("settings.locked") : undefined}
            >
              <Toggle
                id="s-egress"
                label={t("settings.egressGateway")}
                checked={draft.egress_gateway ?? settings.egress_gateway}
                onChange={(v) => set({ egress_gateway: v })}
              />
            </FieldRow>
            {settings.egress_proxy_url ? (
              <p className="m-0 font-mono text-[12.5px] text-muted">{settings.egress_proxy_url}</p>
            ) : null}
            <FieldRow
              label={t("settings.socks5")}
              htmlFor="s-socks"
              hint={t("settings.socks5.hint")}
              locked={locked.includes("socks5_url") ? t("settings.locked") : undefined}
            >
              <input
                id="s-socks"
                className="field font-mono !text-[13.5px]"
                value={String(value("socks5_url", ""))}
                onChange={(e) => set({ socks5_url: e.target.value.trim() })}
                disabled={locked.includes("socks5_url")}
                placeholder="socks5://127.0.0.1:9050"
                dir="ltr"
              />
            </FieldRow>
            <FieldRow label={t("settings.socks5.routes")} hint={t("settings.socks5.routes.hint")}>
              <div className="flex flex-wrap gap-4">
                <label className="inline-flex items-center gap-2 text-[13.5px]">
                  <Toggle
                    label={t("settings.socks5.search")}
                    checked={draft.socks5_for_search ?? settings.socks5_for_search}
                    onChange={(v) => set({ socks5_for_search: v })}
                  />
                  {t("settings.socks5.search")}
                </label>
                <label className="inline-flex items-center gap-2 text-[13.5px]">
                  <Toggle
                    label={t("settings.socks5.fetch")}
                    checked={draft.socks5_for_fetch ?? settings.socks5_for_fetch}
                    onChange={(v) => set({ socks5_for_fetch: v })}
                  />
                  {t("settings.socks5.fetch")}
                </label>
              </div>
            </FieldRow>
            <FieldRow label={t("settings.operatorMetrics")} hint={t("settings.operatorMetrics.hint")}>
              <Toggle
                id="s-metrics"
                label={t("settings.operatorMetrics")}
                checked={draft.operator_metrics ?? settings.operator_metrics}
                onChange={(v) => {
                  if (v && !(draft.operator_metrics ?? settings.operator_metrics)) {
                    setConfirm("metrics");
                  } else set({ operator_metrics: v });
                }}
              />
            </FieldRow>
            <FieldRow label={t("settings.operatorWebhooks")} hint={t("settings.operatorWebhooks.hint")}>
              <Toggle
                id="s-hooks-consent"
                label={t("settings.operatorWebhooks")}
                checked={draft.operator_webhooks ?? settings.operator_webhooks}
                onChange={(v) => {
                  if (v && !(draft.operator_webhooks ?? settings.operator_webhooks)) {
                    setConfirm("webhooks");
                  } else set({ operator_webhooks: v, ...(v ? {} : { webhook_url: "" }) });
                }}
              />
            </FieldRow>
            {(draft.operator_webhooks ?? settings.operator_webhooks) ? (
              <FieldRow
                label={t("settings.webhook")}
                htmlFor="s-hook"
                hint={t("settings.webhook.hint")}
                locked={locked.includes("webhook_url") ? t("settings.locked") : undefined}
              >
                <input
                  id="s-hook"
                  className="field font-mono !text-[13.5px]"
                  value={String(value("webhook_url", ""))}
                  onChange={(e) => set({ webhook_url: e.target.value.trim() })}
                  disabled={locked.includes("webhook_url")}
                  inputMode="url"
                  dir="ltr"
                  placeholder="https://"
                />
              </FieldRow>
            ) : null}
            <p className="m-0 text-[13px] text-muted">
              {t("settings.keychain")}:{" "}
              {settings.keychain_available ? t("settings.keychain.on") : t("settings.keychain.off")}
            </p>
          </Section>

          <Section id="data" title={t("settings.data")} description={t("settings.data.desc")}>
            <FieldRow
              label={t("settings.retention")}
              htmlFor="s-ret"
              hint={t("settings.retention.hint")}
              locked={locked.includes("thread_retention_days") ? t("settings.locked") : undefined}
            >
              <div className="flex items-center gap-2">
                <input
                  id="s-ret"
                  type="number"
                  min={1}
                  max={3650}
                  className="field !w-28 tabular"
                  value={Number(value("thread_retention_days", 28))}
                  onChange={(e) =>
                    set({ thread_retention_days: Math.max(1, Math.min(3650, Number(e.target.value) || 28)) })
                  }
                  disabled={locked.includes("thread_retention_days")}
                />
                <span className="text-sm text-muted">{t("settings.days")}</span>
              </div>
            </FieldRow>
            <div className="flex flex-wrap gap-2">
              <Button onClick={() => setConfirm("cache")}>{t("settings.clearCache")}</Button>
              <Button variant="danger" onClick={() => setConfirm("wipe")}>
                {t("settings.wipe")}
              </Button>
            </div>
          </Section>

          <Section id="appearance" title={t("settings.appearance")}>
            <FieldRow label={t("settings.theme")}>
              <Segmented<Theme>
                label={t("settings.theme")}
                value={prefs.theme}
                onChange={(theme) => setPrefs({ theme })}
                options={[
                  { value: "system", label: t("theme.system") },
                  { value: "light", label: t("theme.light") },
                  { value: "dark", label: t("theme.dark") },
                ]}
              />
            </FieldRow>
            <FieldRow label={t("settings.accent")}>
              <div role="radiogroup" aria-label={t("settings.accent")} className="flex flex-wrap gap-2.5">
                {ACCENTS.map((a) => (
                  <button
                    key={a}
                    type="button"
                    role="radio"
                    aria-checked={prefs.accent === a}
                    aria-label={t(`accent.${a}` as never)}
                    onClick={() => setPrefs({ accent: a })}
                    className={cn(
                      "grid size-8 place-items-center rounded-full ring-offset-2 ring-offset-surface transition-shadow",
                      prefs.accent === a && "ring-2 ring-fg",
                    )}
                    style={{ background: SWATCH[a] }}
                  >
                    {prefs.accent === a ? <Check className="size-4 text-white" strokeWidth={3} aria-hidden /> : null}
                  </button>
                ))}
              </div>
            </FieldRow>
            <FieldRow label={t("settings.language")} htmlFor="s-lang" hint={t("settings.language.hint")}>
              <select
                id="s-lang"
                className="field !w-56"
                value={preference}
                onChange={(e) => setPreference(e.target.value)}
              >
                <option value="auto">{t("settings.language.auto")}</option>
                {LOCALES.map((l) => (
                  <option key={l.code} value={l.code}>
                    {l.name}
                  </option>
                ))}
              </select>
            </FieldRow>
          </Section>

          <Section id="advanced" title={t("settings.advanced")}>
            <FieldRow
              label={t("settings.searchLocale")}
              htmlFor="s-loc"
              hint={t("settings.searchLocale.hint")}
              locked={locked.includes("locale") ? t("settings.locked") : undefined}
            >
              <input
                id="s-loc"
                className="field !w-40"
                value={String(value("locale", ""))}
                onChange={(e) => set({ locale: e.target.value.trim() })}
                placeholder="auto"
                disabled={locked.includes("locale")}
                dir="ltr"
              />
            </FieldRow>
            <dl className="m-0 grid grid-cols-[auto_1fr] gap-x-6 gap-y-1.5 text-[13.5px]">
              <dt className="text-muted">{t("settings.version")}</dt>
              <dd className="m-0 tabular">{settings.version}</dd>
              <dt className="text-muted">{t("settings.profile")}</dt>
              <dd className="m-0">{settings.profile}</dd>
              <dt className="text-muted">{t("settings.auth")}</dt>
              <dd className="m-0">{settings.auth_required ? t("settings.auth.on") : t("settings.auth.off")}</dd>
            </dl>
          </Section>
        </div>
      </div>

      {dirty ? (
        <div
          role="region"
          aria-label={t("settings.unsaved")}
          className="fixed inset-x-0 bottom-4 z-20 mx-auto flex w-[min(92vw,34rem)] items-center gap-3 rounded-full border border-border-strong bg-surface py-2 ps-5 pe-2 shadow-[var(--shadow-pop)] rise lg:ms-[calc(50%-17rem+var(--sidebar-w)/2)]"
        >
          <span className="flex-1 text-sm font-medium">{t("settings.unsaved")}</span>
          <Button variant="ghost" size="sm" onClick={() => (setDraft({}), setRemoveKey(false))} disabled={saving}>
            {t("settings.discard")}
          </Button>
          <Button variant="primary" size="sm" onClick={() => void save()} busy={saving}>
            {t("common.save")}
          </Button>
        </div>
      ) : null}

      <ConfirmDialog
        open={confirm === "cache"}
        onOpenChange={(o) => !o && setConfirm(null)}
        title={t("settings.clearCache.title")}
        body={t("settings.clearCache.body")}
        confirmLabel={t("settings.clearCache")}
        onConfirm={() =>
          void client.clearCache().then(
            () => toast({ title: t("settings.cacheCleared"), tone: "success" }),
            (e: unknown) =>
              toast({
                title: t("toast.actionFailed"),
                body: e instanceof Error ? e.message : undefined,
                tone: "error",
              }),
          )
        }
      />
      <ConfirmDialog
        open={confirm === "metrics"}
        onOpenChange={(o) => {
          if (!o) setConfirm(null);
        }}
        title={t("settings.consent.metrics.title")}
        body={t("settings.consent.metrics.body")}
        confirmLabel={t("settings.consent.enable")}
        onConfirm={() => {
          set({ operator_metrics: true });
        }}
      />
      <ConfirmDialog
        open={confirm === "webhooks"}
        onOpenChange={(o) => {
          if (!o) setConfirm(null);
        }}
        title={t("settings.consent.webhooks.title")}
        body={t("settings.consent.webhooks.body")}
        confirmLabel={t("settings.consent.enable")}
        onConfirm={() => {
          set({ operator_webhooks: true });
        }}
      />
      <Modal
        open={confirm === "wipe"}
        onOpenChange={(o) => {
          if (!o) {
            setConfirm(null);
            setWipeText("");
          }
        }}
        title={t("settings.wipe.title")}
        description={t("settings.wipe.body")}
        footer={
          <>
            <Button onClick={() => setConfirm(null)}>{t("common.cancel")}</Button>
            <Button
              variant="danger"
              disabled={wipeText.trim().toLowerCase() !== t("settings.wipe.word").toLowerCase()}
              onClick={() => {
                setConfirm(null);
                setWipeText("");
                void client.wipeData().then(
                  () => {
                    toast({ title: t("settings.wiped"), tone: "success" });
                    location.assign("/");
                  },
                  (e: unknown) =>
                    toast({
                      title: t("toast.actionFailed"),
                      body: e instanceof Error ? e.message : undefined,
                      tone: "error",
                    }),
                );
              }}
            >
              {t("settings.wipe")}
            </Button>
          </>
        }
      >
        <FieldRow label={t("settings.wipe.type", { word: t("settings.wipe.word") })} htmlFor="wipe-confirm">
          <input
            id="wipe-confirm"
            className="field"
            value={wipeText}
            onChange={(e) => setWipeText(e.target.value)}
            autoComplete="off"
          />
        </FieldRow>
      </Modal>
    </div>
  );
}
