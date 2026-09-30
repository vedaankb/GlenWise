// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 Ved Buddaraju

import * as Dialog from "@radix-ui/react-dialog";
import * as Tooltip from "@radix-ui/react-tooltip";
import { Loader2 } from "lucide-react";
import type { ButtonHTMLAttributes, ReactNode } from "react";
import { cn } from "@/lib/cn";
import { useT } from "@/i18n";

export function Spinner({ className }: { className?: string }) {
  return <Loader2 className={cn("spin size-4", className)} aria-hidden />;
}

type Variant = "primary" | "secondary" | "ghost" | "danger";
export function Button({
  variant = "secondary",
  size,
  icon,
  className,
  busy,
  children,
  ...rest
}: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: Variant; size?: "sm"; icon?: boolean; busy?: boolean }) {
  return (
    <button
      type="button"
      className={cn("btn", `btn-${variant}`, size === "sm" && "btn-sm", icon && "btn-icon", className)}
      aria-busy={busy || undefined}
      {...rest}
      disabled={rest.disabled || busy}
    >
      {busy ? <Spinner /> : null}
      {children}
    </button>
  );
}

/** Icon-only button: the label is required so it is always named for assistive tech, and shown as a tooltip. */
export function IconButton({
  label,
  children,
  variant = "ghost",
  size,
  tip = true,
  ...rest
}: ButtonHTMLAttributes<HTMLButtonElement> & { label: string; variant?: Variant; size?: "sm"; tip?: boolean }) {
  const btn = (
    <button
      type="button"
      aria-label={label}
      className={cn("btn", `btn-${variant}`, "btn-icon", size === "sm" && "btn-sm")}
      {...rest}
    >
      {children}
    </button>
  );
  return tip ? <Tip label={label}>{btn}</Tip> : btn;
}

export function Tip({
  label,
  children,
  side = "top",
}: {
  label: string;
  children: ReactNode;
  side?: "top" | "bottom" | "left" | "right";
}) {
  return (
    <Tooltip.Root delayDuration={350}>
      <Tooltip.Trigger asChild>{children}</Tooltip.Trigger>
      <Tooltip.Portal>
        <Tooltip.Content side={side} sideOffset={6} className="tooltip">
          {label}
        </Tooltip.Content>
      </Tooltip.Portal>
    </Tooltip.Root>
  );
}

export function Modal({
  open,
  onOpenChange,
  title,
  description,
  children,
  footer,
}: {
  open: boolean;
  onOpenChange(o: boolean): void;
  title: string;
  description?: string;
  children?: ReactNode;
  footer?: ReactNode;
}) {
  return (
    <Dialog.Root open={open} onOpenChange={onOpenChange}>
      <Dialog.Portal>
        <Dialog.Overlay className="overlay" />
        <Dialog.Content className="dialog" aria-describedby={description ? undefined : undefined}>
          <Dialog.Title className="text-lg font-semibold tracking-tight">{title}</Dialog.Title>
          {description ? (
            <Dialog.Description className="mt-1 text-sm text-muted">{description}</Dialog.Description>
          ) : (
            <Dialog.Description className="sr-only">{title}</Dialog.Description>
          )}
          {children ? <div className="mt-4">{children}</div> : null}
          {footer ? <div className="mt-6 flex justify-end gap-2">{footer}</div> : null}
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}

export function ConfirmDialog({
  open,
  onOpenChange,
  title,
  body,
  confirmLabel,
  onConfirm,
  danger,
}: {
  open: boolean;
  onOpenChange(o: boolean): void;
  title: string;
  body: string;
  confirmLabel: string;
  onConfirm(): void;
  danger?: boolean;
}) {
  const t = useT();
  return (
    <Modal
      open={open}
      onOpenChange={onOpenChange}
      title={title}
      description={body}
      footer={
        <>
          <Button onClick={() => onOpenChange(false)}>{t("common.cancel")}</Button>
          <Button
            variant={danger ? "danger" : "primary"}
            onClick={() => {
              onOpenChange(false);
              onConfirm();
            }}
          >
            {confirmLabel}
          </Button>
        </>
      }
    />
  );
}

export function StatusDot({ ok, pending, className }: { ok?: boolean; pending?: boolean; className?: string }) {
  return (
    <span
      aria-hidden
      className={cn(
        "inline-block size-2 rounded-full",
        pending ? "bg-subtle" : ok ? "bg-success" : "bg-danger",
        className,
      )}
    />
  );
}

import * as RadioGroup from "@radix-ui/react-radio-group";
import * as Switch from "@radix-ui/react-switch";

export function Segmented<T extends string>({
  value,
  onChange,
  options,
  label,
}: {
  value: T;
  onChange(v: T): void;
  options: { value: T; label: string }[];
  label: string;
}) {
  return (
    <RadioGroup.Root
      value={value}
      onValueChange={(v) => onChange(v as T)}
      aria-label={label}
      className="inline-flex rounded-full bg-surface-2 p-0.5"
    >
      {options.map((o) => (
        <RadioGroup.Item
          key={o.value}
          value={o.value}
          className="rounded-full px-3.5 py-1.5 text-[13.5px] font-medium text-muted transition-colors hover:text-fg data-[state=checked]:bg-surface data-[state=checked]:text-fg data-[state=checked]:shadow-sm"
        >
          {o.label}
        </RadioGroup.Item>
      ))}
    </RadioGroup.Root>
  );
}

export function Toggle({
  checked,
  onChange,
  label,
  id,
}: {
  checked: boolean;
  onChange(v: boolean): void;
  label: string;
  id?: string;
}) {
  return (
    <Switch.Root
      id={id}
      checked={checked}
      onCheckedChange={onChange}
      aria-label={label}
      className="relative h-6 w-10 rounded-full bg-surface-3 transition-colors data-[state=checked]:bg-accent"
    >
      <Switch.Thumb className="block size-5 translate-x-0.5 rounded-full bg-white shadow transition-transform data-[state=checked]:translate-x-[18px] rtl:-translate-x-0.5 rtl:data-[state=checked]:-translate-x-[18px]" />
    </Switch.Root>
  );
}

export function FieldRow({
  label,
  htmlFor,
  hint,
  children,
  locked,
}: {
  label: string;
  htmlFor?: string;
  hint?: ReactNode;
  children: ReactNode;
  locked?: string;
}) {
  return (
    <div className="grid gap-1.5">
      <label htmlFor={htmlFor} className="text-[13.5px] font-semibold">
        {label}
      </label>
      {children}
      {locked ? (
        <p className="m-0 text-[12.5px] text-muted">{locked}</p>
      ) : hint ? (
        <p className="m-0 text-[12.5px] text-muted">{hint}</p>
      ) : null}
    </div>
  );
}
