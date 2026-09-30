// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 Ved Buddaraju

import type { HealthComponent, SettingsView } from "@gleanwise/react";
import { Check, ExternalLink, Lock, X } from "lucide-react";
import { useState } from "react";
import { useT, type Key } from "@/i18n";
import { cn } from "@/lib/cn";
import { Link } from "@/router";
import { Button, FieldRow, Spinner } from "./ui";

export interface Provider {
  id: string;
  label: string;
  prefix: string;
  base?: string;
  needsKey: boolean;
  models: string[];
  help: Key;
  keyUrl?: string;
}

export const PROVIDERS: Provider[] = [
  {
    id: "openai",
    label: "OpenAI",
    prefix: "openai/",
    needsKey: true,
    models: ["gpt-4o-mini", "gpt-4o", "gpt-4.1-mini"],
    help: "provider.openai.help",
    keyUrl: "https://platform.openai.com/api-keys",
  },
  {
    id: "anthropic",
    label: "Anthropic",
    prefix: "anthropic/",
    needsKey: true,
    models: ["claude-sonnet-4-5", "claude-haiku-4-5"],
    help: "provider.anthropic.help",
    keyUrl: "https://console.anthropic.com/settings/keys",
  },
  {
    id: "gemini",
    label: "Google Gemini",
    prefix: "gemini/",
    needsKey: true,
    models: ["gemini-2.5-flash", "gemini-2.5-pro"],
    help: "provider.gemini.help",
    keyUrl: "https://aistudio.google.com/apikey",
  },
  {
    id: "openrouter",
    label: "OpenRouter",
    prefix: "openrouter/",
    needsKey: true,
    models: ["openai/gpt-4o-mini", "anthropic/claude-sonnet-4.5"],
    help: "provider.openrouter.help",
    keyUrl: "https://openrouter.ai/keys",
  },
  {
    id: "ollama",
    label: "Ollama (local)",
    prefix: "ollama_chat/",
    base: "http://localhost:11434",
    needsKey: false,
    models: ["llama3.1", "qwen2.5"],
    help: "provider.ollama.help",
  },
  {
    id: "custom",
    label: "OpenAI-compatible",
    prefix: "openai/",
    needsKey: false,
    models: [],
    help: "provider.custom.help",
  },
];

export function providerOf(model: string, base: string): Provider {
  const byPrefix = PROVIDERS.filter((p) => p.id !== "custom").find(
    (p) => model.startsWith(p.prefix) && !(p.id === "openai" && base),
  );
  return byPrefix ?? (model ? PROVIDERS[PROVIDERS.length - 1] : PROVIDERS[0]);
}

export interface LlmDraft {
  llm_model: string;
  llm_api_key: string;
  llm_api_base: string;
}

/** Provider, model and key. The model box starts empty: suggestions help, but nothing is chosen for you. */
export function LlmFields({
  draft,
  onChange,
  settings,
  provider,
  onProvider,
  lockedFields = [],
}: {
  draft: LlmDraft;
  onChange(p: Partial<LlmDraft>): void;
  settings: SettingsView | null;
  provider: Provider;
  onProvider(p: Provider): void;
  lockedFields?: string[];
}) {
  const t = useT();
  const lockMsg = t("settings.locked");
  const modelLocked = lockedFields.includes("llm_model");
  const keyLocked = lockedFields.includes("llm_api_key");
  const baseLocked = lockedFields.includes("llm_api_base");
  const [showBase, setShowBase] = useState(
    !!draft.llm_api_base || provider.id === "custom" || provider.id === "ollama",
  );
  return (
    <div className="grid gap-5">
      <fieldset className="m-0 grid gap-2 border-0 p-0">
        <legend className="mb-1 text-[13.5px] font-semibold">{t("llm.provider")}</legend>
        <div className="grid grid-cols-2 gap-2 sm:grid-cols-3" role="radiogroup" aria-label={t("llm.provider")}>
          {PROVIDERS.map((p) => (
            <button
              key={p.id}
              type="button"
              role="radio"
              aria-checked={provider.id === p.id}
              disabled={modelLocked}
              onClick={() => {
                onProvider(p);
                setShowBase(p.id === "custom" || p.id === "ollama");
                onChange({
                  llm_api_base: p.base ?? "",
                  ...(draft.llm_model.startsWith(provider.prefix) || !draft.llm_model ? { llm_model: "" } : {}),
                });
              }}
              className={cn(
                "rounded-[var(--radius)] border px-3 py-2.5 text-start text-[13.5px] font-medium transition-colors",
                provider.id === p.id
                  ? "border-accent bg-accent/8 text-fg shadow-[0_0_0_1px_var(--accent)]"
                  : "border-border-strong bg-surface hover:bg-surface-2",
                "disabled:opacity-50",
              )}
            >
              {p.label}
            </button>
          ))}
        </div>
        <p className="m-0 text-[12.5px] text-muted">
          {t(provider.help)}{" "}
          {provider.keyUrl ? (
            <a
              href={provider.keyUrl}
              target="_blank"
              rel="noopener noreferrer"
              className="inline-flex items-center gap-1 text-accent-text underline underline-offset-2"
            >
              {t("llm.getKey")}
              <ExternalLink className="size-3" aria-hidden />
            </a>
          ) : null}
        </p>
      </fieldset>

      <FieldRow
        label={t("llm.model")}
        htmlFor="llm-model"
        hint={t("llm.model.hint", { prefix: provider.prefix })}
        locked={modelLocked ? lockMsg : undefined}
      >
        <input
          id="llm-model"
          className="field font-mono !text-[13.5px]"
          value={draft.llm_model}
          onChange={(e) => onChange({ llm_model: e.target.value.trim() })}
          placeholder={`${provider.prefix}…`}
          disabled={modelLocked}
          spellCheck={false}
          autoCapitalize="off"
          autoCorrect="off"
          dir="ltr"
        />
        {provider.models.length && !modelLocked ? (
          <div className="flex flex-wrap items-center gap-1.5" aria-label={t("llm.suggestions")}>
            <span className="text-[12.5px] text-muted">{t("llm.suggestions")}</span>
            {provider.models.map((m) => {
              const full =
                m.includes("/") && provider.id === "openrouter" ? `${provider.prefix}${m}` : `${provider.prefix}${m}`;
              return (
                <button
                  key={m}
                  type="button"
                  onClick={() => onChange({ llm_model: full })}
                  className="rounded-full border border-border bg-surface px-2.5 py-0.5 font-mono text-[12px] hover:bg-surface-2"
                >
                  {m}
                </button>
              );
            })}
          </div>
        ) : null}
      </FieldRow>

      {provider.needsKey || provider.id === "custom" ? (
        <FieldRow
          label={t("llm.key")}
          htmlFor="llm-key"
          hint={
            settings?.llm_api_key_set && !draft.llm_api_key
              ? t("llm.key.saved")
              : provider.needsKey
                ? t("llm.key.hint")
                : t("llm.key.optional")
          }
          locked={keyLocked ? lockMsg : undefined}
        >
          <input
            id="llm-key"
            type="password"
            className="field font-mono !text-[13.5px]"
            value={draft.llm_api_key}
            onChange={(e) => onChange({ llm_api_key: e.target.value.trim() })}
            placeholder={settings?.llm_api_key_set ? "••••••••••••" : t("llm.key.placeholder")}
            autoComplete="off"
            disabled={keyLocked}
            spellCheck={false}
            dir="ltr"
          />
        </FieldRow>
      ) : null}

      {showBase || provider.id === "ollama" ? (
        <FieldRow
          label={t("llm.base")}
          htmlFor="llm-base"
          hint={t("llm.base.hint", { example: provider.base ?? "http://localhost:1234/v1" })}
          locked={baseLocked ? lockMsg : undefined}
        >
          <input
            id="llm-base"
            className="field font-mono !text-[13.5px]"
            value={draft.llm_api_base}
            onChange={(e) => onChange({ llm_api_base: e.target.value.trim() })}
            placeholder={provider.base ?? "http://localhost:1234/v1"}
            disabled={baseLocked}
            inputMode="url"
            spellCheck={false}
            dir="ltr"
          />
        </FieldRow>
      ) : (
        <button
          type="button"
          className="w-fit text-[13px] text-accent-text underline underline-offset-2"
          onClick={() => setShowBase(true)}
        >
          {t("llm.base.show")}
        </button>
      )}
    </div>
  );
}

const LABEL: Record<string, Key> = {
  llm: "diag.llm",
  search: "diag.search",
  embeddings: "diag.embeddings",
  storage: "diag.storage",
  browser: "diag.browser",
  ranking: "diag.ranking",
};

export function ComponentRow({ c, pending }: { c: HealthComponent; pending?: boolean }) {
  const t = useT();
  const label = LABEL[c.name] ? t(LABEL[c.name]) : c.name;
  return (
    <li className="flex items-start gap-3 py-3">
      <span
        className={cn(
          "mt-0.5 grid size-6 shrink-0 place-items-center rounded-full",
          pending ? "bg-surface-3" : c.ok ? "bg-success/15 text-success" : "bg-danger/15 text-danger",
        )}
      >
        {pending ? (
          <Spinner className="size-3.5" />
        ) : c.ok ? (
          <Check className="size-3.5" strokeWidth={3} aria-hidden />
        ) : (
          <X className="size-3.5" strokeWidth={3} aria-hidden />
        )}
      </span>
      <div className="min-w-0 flex-1">
        <p className="m-0 text-[14.5px] font-semibold">
          {label} <span className="sr-only">{c.ok ? t("diag.ok") : t("diag.failing")}</span>
        </p>
        <p className="m-0 mt-0.5 break-words text-[13.5px] text-muted">{c.detail}</p>
        {!c.ok && c.hint ? <p className="m-0 mt-1 text-[13.5px]">{c.hint}</p> : null}
        {!c.ok && c.action === "open_settings" ? (
          <Link to="/settings" className="btn btn-secondary btn-sm mt-2">
            {t("error.openSettings")}
          </Link>
        ) : null}
      </div>
    </li>
  );
}

export function TestResults({
  results,
  running,
}: {
  results: { llm: HealthComponent; search: HealthComponent; embeddings: HealthComponent } | null;
  running: boolean;
}) {
  const t = useT();
  const rows = results ? [results.llm, results.search, results.embeddings] : [];
  const placeholder = (name: string): HealthComponent => ({
    name,
    ok: false,
    detail: t("test.checking"),
    hint: null,
    action: null,
  });
  return (
    <div className="card px-4" aria-live="polite" aria-busy={running}>
      <ul className="m-0 list-none divide-y divide-border p-0">
        {running
          ? ["llm", "search", "embeddings"].map((n) => <ComponentRow key={n} c={placeholder(n)} pending />)
          : rows.map((c) => <ComponentRow key={c.name} c={c} />)}
      </ul>
    </div>
  );
}

export function TestButton({ onRun, running, disabled }: { onRun(): void; running: boolean; disabled?: boolean }) {
  const t = useT();
  return (
    <Button onClick={onRun} busy={running} disabled={disabled}>
      {running ? t("test.running") : t("test.run")}
    </Button>
  );
}

export function LockNote() {
  const t = useT();
  return (
    <span className="inline-flex items-center gap-1 text-[12.5px] text-muted">
      <Lock className="size-3" aria-hidden />
      {t("settings.locked")}
    </span>
  );
}
