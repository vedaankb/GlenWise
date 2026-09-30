// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 Ved Buddaraju

import * as Popover from "@radix-ui/react-popover";
import { useEffect, useRef, useState, type ReactNode } from "react";
import { useLabels } from "./labels";
import { safeUrl } from "./text";

export interface CitationInfo {
  number: number;
  url: string;
  title: string;
  domain?: string;
  excerpt?: string;
  favicon?: string;
}

export interface CitationChipProps {
  info: CitationInfo;
  /** Called just before navigating, so apps can save scroll/state for the back button. */
  onOpen?(info: CitationInfo): void;
  /** Same-tab navigation is the default (Back returns to the thread). */
  target?: "_self" | "_blank";
  renderPreview?(info: CitationInfo): ReactNode;
  className?: string;
}

/**
 * A numbered link with a preview card. The card opens on mouse hover, keyboard focus, or the first tap
 * on touch screens (a second tap follows the link), and closes on Escape. The chip is a real anchor, so
 * middle-click, "open in new tab" and screen readers all behave.
 */
export function CitationChip({ info, onOpen, target = "_self", renderPreview, className }: CitationChipProps) {
  const t = useLabels();
  const [open, setOpen] = useState(false);
  const timer = useRef<number | undefined>(undefined);
  const pointer = useRef<string>("mouse");
  useEffect(() => () => window.clearTimeout(timer.current), []);
  const schedule = (next: boolean, delay: number) => {
    window.clearTimeout(timer.current);
    timer.current = window.setTimeout(() => setOpen(next), delay);
  };
  const href = safeUrl(info.url);
  const label = `${t.source(info.number)}: ${info.title || info.domain || info.url}`;

  const chip = (
    <a
      className={className ?? "gw-cite"}
      data-gw="citation"
      href={href ?? undefined}
      target={target}
      rel={target === "_blank" ? "noopener noreferrer" : "noreferrer"}
      aria-label={label}
      aria-expanded={open}
      onPointerDown={(e) => (pointer.current = e.pointerType)}
      onPointerEnter={(e) => e.pointerType === "mouse" && schedule(true, 120)}
      onPointerLeave={(e) => e.pointerType === "mouse" && schedule(false, 160)}
      onFocus={() => schedule(true, 0)}
      onBlur={() => schedule(false, 120)}
      onClick={(e) => {
        if (pointer.current === "touch" && !open) {
          e.preventDefault();
          setOpen(true);
          return;
        }
        onOpen?.(info);
      }}
    >
      {info.number}
    </a>
  );

  return (
    <Popover.Root open={open} onOpenChange={setOpen}>
      <Popover.Anchor asChild>{chip}</Popover.Anchor>
      <Popover.Portal>
        <Popover.Content
          className="gw-cite-card"
          data-gw="citation-card"
          sideOffset={6}
          collisionPadding={12}
          onOpenAutoFocus={(e) => e.preventDefault()}
          onCloseAutoFocus={(e) => e.preventDefault()}
          onPointerEnter={() => schedule(true, 0)}
          onPointerLeave={() => schedule(false, 160)}
        >
          {renderPreview ? (
            renderPreview(info)
          ) : (
            <>
              <div className="gw-cite-card-head">
                {info.favicon ? <img src={info.favicon} alt="" width={16} height={16} loading="lazy" /> : null}
                <span>{info.domain}</span>
              </div>
              <strong className="gw-cite-card-title">{info.title || info.url}</strong>
              {info.excerpt ? <p className="gw-cite-card-excerpt">{info.excerpt}</p> : null}
              {href ? (
                <a className="gw-cite-card-link" href={href} onClick={() => onOpen?.(info)}>
                  {t.openSource}
                </a>
              ) : null}
            </>
          )}
        </Popover.Content>
      </Popover.Portal>
    </Popover.Root>
  );
}
