// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 Ved Buddaraju

import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { ar } from "./ar";
import { en } from "./en";

export type Key = keyof typeof en;
export type Locale = "en" | "ar";
type Params = Record<string, string | number>;

export const LOCALES: { code: Locale; name: string; dir: "ltr" | "rtl" }[] = [
  { code: "en", name: "English", dir: "ltr" },
  { code: "ar", name: "العربية", dir: "rtl" },
];
const DICTS: Record<Locale, Partial<Record<Key, string>>> = { en, ar };
const STORE = "gleanwise.locale";

export function resolveLocale(pref: string | null | undefined, languages: readonly string[] = []): Locale {
  const codes = LOCALES.map((l) => l.code as string);
  if (pref && pref !== "auto" && codes.includes(pref)) return pref as Locale;
  for (const l of languages) {
    const base = l.toLowerCase().split("-")[0];
    if (codes.includes(base)) return base as Locale;
  }
  return "en";
}

/** Look up a string, choose a plural form from `count` with Intl.PluralRules, and fill `{name}` slots. */
export function translate(locale: Locale, key: Key, params?: Params): string {
  const dict = DICTS[locale];
  let raw: string | undefined;
  if (params && typeof params.count === "number") {
    const rule = new Intl.PluralRules(locale).select(params.count);
    raw =
      dict[`${key}_${rule}` as Key] ??
      dict[`${key}_other` as Key] ??
      en[`${key}_${rule}` as Key] ??
      en[`${key}_other` as Key];
  }
  raw ??= dict[key] ?? en[key] ?? key;
  return params ? raw.replace(/\{(\w+)\}/g, (_m, k: string) => (k in params ? String(params[k]) : `{${k}}`)) : raw;
}

interface I18n {
  locale: Locale;
  /** The stored preference: a locale or "auto". */
  preference: string;
  dir: "ltr" | "rtl";
  t: (key: Key, params?: Params) => string;
  setPreference(p: string): void;
  date(iso: string | number | Date, opts?: Intl.DateTimeFormatOptions): string;
  number(n: number, opts?: Intl.NumberFormatOptions): string;
}

const Ctx = createContext<I18n | null>(null);

export function I18nProvider({ children }: { children: ReactNode }) {
  const [preference, setPref] = useState(() => localStorage.getItem(STORE) ?? "auto");
  const locale = resolveLocale(preference, navigator.languages);
  const dir = LOCALES.find((l) => l.code === locale)!.dir;
  useEffect(() => {
    document.documentElement.lang = locale;
    document.documentElement.dir = dir;
  }, [locale, dir]);
  const setPreference = useCallback((p: string) => {
    localStorage.setItem(STORE, p);
    setPref(p);
  }, []);
  const value = useMemo<I18n>(
    () => ({
      locale,
      preference,
      dir,
      t: (key, params) => translate(locale, key, params),
      setPreference,
      date: (d, o) => new Intl.DateTimeFormat(locale, o ?? { dateStyle: "medium" }).format(new Date(d)),
      number: (n, o) => new Intl.NumberFormat(locale, o).format(n),
    }),
    [locale, preference, dir, setPreference],
  );
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useI18n(): I18n {
  const v = useContext(Ctx);
  if (!v) throw new Error("useI18n outside I18nProvider");
  return v;
}
export const useT = () => useI18n().t;
