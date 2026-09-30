// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 Ved Buddaraju

import * as DropdownMenu from "@radix-ui/react-dropdown-menu";
import * as RadioGroup from "@radix-ui/react-radio-group";
import type { Focus, Mode } from "@gleanwise/react";
import {
  ArrowUp,
  Check,
  ChevronDown,
  GraduationCap,
  Globe,
  Lock,
  MessagesSquare,
  Newspaper,
  Square,
} from "lucide-react";
import { forwardRef, useEffect, useImperativeHandle, useLayoutEffect, useRef, type ComponentType } from "react";
import { cn } from "@/lib/cn";
import { useT, type Key } from "@/i18n";
import { Tip } from "./ui";

const MODES: { id: Mode; label: Key; hint: Key; key: string }[] = [
  { id: "quick", label: "mode.quick", hint: "mode.quick.hint", key: "1" },
  { id: "pro", label: "mode.pro", hint: "mode.pro.hint", key: "2" },
  { id: "deep", label: "mode.deep", hint: "mode.deep.hint", key: "3" },
];
export const FOCUSES: { id: Focus; label: Key; icon: ComponentType<{ className?: string }> }[] = [
  { id: "general", label: "focus.general", icon: Globe },
  { id: "academic", label: "focus.academic", icon: GraduationCap },
  { id: "news", label: "focus.news", icon: Newspaper },
  { id: "social", label: "focus.social", icon: MessagesSquare },
];

export interface ComposerHandle {
  focus(): void;
}
interface Props {
  value: string;
  onChange(v: string): void;
  onSubmit(): void;
  mode: Mode;
  onMode(m: Mode): void;
  focusMode: Focus;
  onFocusMode(f: Focus): void;
  busy?: boolean;
  onStop?(): void;
  placeholder?: string;
  variant?: "hero" | "dock";
  autoFocus?: boolean;
  label: string;
  /** D6: show lock badge — search is not written to history. */
  privateMode?: boolean;
}

/** The search box: Enter sends, Shift+Enter adds a line, and IME composition never sends by accident. */
export const Composer = forwardRef<ComposerHandle, Props>(function Composer(
  {
    value,
    onChange,
    onSubmit,
    mode,
    onMode,
    focusMode,
    onFocusMode,
    busy,
    onStop,
    placeholder,
    variant = "dock",
    autoFocus,
    label,
    privateMode,
  },
  ref,
) {
  const t = useT();
  const area = useRef<HTMLTextAreaElement>(null);
  useImperativeHandle(ref, () => ({ focus: () => area.current?.focus() }));
  useEffect(() => {
    if (autoFocus) area.current?.focus();
  }, [autoFocus]);
  useLayoutEffect(() => {
    const el = area.current;
    if (!el) return;
    el.style.blockSize = "auto";
    el.style.blockSize = `${Math.min(el.scrollHeight, 200)}px`;
  }, [value]);

  const canSend = value.trim().length > 0 && !busy;
  const Focus = FOCUSES.find((f) => f.id === focusMode)!;
  return (
    <form
      role="search"
      aria-label={label}
      onSubmit={(e) => {
        e.preventDefault();
        if (canSend) onSubmit();
      }}
      className={cn(
        "group/composer gw-composer glow relative rounded-[var(--radius-xl)] border border-border-strong bg-surface transition-[box-shadow,border-color] duration-200",
        "focus-within:border-accent focus-within:shadow-[0_0_0_4px_var(--ring)]",
        variant === "hero" ? "shadow-md" : "shadow-md backdrop-blur",
      )}
    >
      <label htmlFor="composer-input" className="sr-only">
        {label}
      </label>
      <textarea
        id="composer-input"
        ref={area}
        rows={1}
        value={value}
        placeholder={placeholder}
        onChange={(e) => onChange(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing && e.keyCode !== 229) {
            e.preventDefault();
            if (canSend) onSubmit();
          }
        }}
        className={cn(
          "block w-full resize-none bg-transparent px-5 pt-4 pb-1 outline-none placeholder:text-subtle",
          variant === "hero" ? "text-[17px] leading-7" : "text-[15.5px] leading-6",
        )}
        style={{ maxBlockSize: 200 }}
        enterKeyHint="send"
        autoComplete="off"
        spellCheck
      />
      <div className="flex items-center gap-2 px-3 pt-1 pb-3">
        {privateMode ? (
          <Tip label={t("private.badge.hint")}>
            <span className="inline-flex items-center gap-1 rounded-full bg-surface-2 px-2.5 py-1 text-[12.5px] font-medium text-fg">
              <Lock className="size-3.5" aria-hidden />
              {t("private.badge")}
            </span>
          </Tip>
        ) : null}
        <RadioGroup.Root
          value={mode}
          onValueChange={(v) => onMode(v as Mode)}
          aria-label={t("composer.mode")}
          className="flex rounded-full bg-surface-2 p-0.5"
          orientation="horizontal"
        >
          {MODES.map((m) => (
            <Tip key={m.id} label={`${t(m.hint)} · Alt+${m.key}`}>
              <RadioGroup.Item
                value={m.id}
                className="relative rounded-full px-3 py-1 text-[13px] font-medium text-muted transition-colors hover:text-fg data-[state=checked]:bg-accent data-[state=checked]:text-accent-fg data-[state=checked]:shadow-sm"
              >
                {t(m.label)}
              </RadioGroup.Item>
            </Tip>
          ))}
        </RadioGroup.Root>

        <DropdownMenu.Root>
          <DropdownMenu.Trigger asChild>
            <button
              type="button"
              className="btn btn-ghost btn-sm gap-1.5 !px-2.5"
              aria-label={`${t("composer.focus")}: ${t(Focus.label)}`}
            >
              <Focus.icon className="size-4" />
              <span className="hidden sm:inline">{t(Focus.label)}</span>
              <ChevronDown className="size-3.5 opacity-60" />
            </button>
          </DropdownMenu.Trigger>
          <DropdownMenu.Portal>
            <DropdownMenu.Content className="menu" align="start" sideOffset={6}>
              <DropdownMenu.Label className="menu-label">{t("composer.focus")}</DropdownMenu.Label>
              <DropdownMenu.RadioGroup value={focusMode} onValueChange={(v) => onFocusMode(v as Focus)}>
                {FOCUSES.map((f) => (
                  <DropdownMenu.RadioItem key={f.id} value={f.id} className="menu-item">
                    <f.icon className="size-4 text-muted" />
                    <span className="flex-1">{t(f.label)}</span>
                    <DropdownMenu.ItemIndicator>
                      <Check className="size-4 text-accent-text" />
                    </DropdownMenu.ItemIndicator>
                  </DropdownMenu.RadioItem>
                ))}
              </DropdownMenu.RadioGroup>
            </DropdownMenu.Content>
          </DropdownMenu.Portal>
        </DropdownMenu.Root>

        <div className="ms-auto flex items-center gap-2">
          {busy ? (
            <Tip label={t("composer.stop")}>
              <button
                type="button"
                onClick={onStop}
                aria-label={t("composer.stop")}
                className="btn btn-secondary btn-icon !rounded-full"
              >
                <Square className="size-3.5 fill-current" />
              </button>
            </Tip>
          ) : (
            <button
              type="submit"
              disabled={!canSend}
              aria-label={t("composer.send")}
              className="btn btn-primary btn-icon !rounded-full"
            >
              <ArrowUp className="size-[18px]" strokeWidth={2.4} />
            </button>
          )}
        </div>
      </div>
    </form>
  );
});
