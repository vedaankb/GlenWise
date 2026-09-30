"use client";

// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 Ved Buddaraju

import type { CSSProperties, ReactNode } from "react";

export interface CitationChipProps {
  number: number;
  excerpt?: string;
  url?: string;
  title?: string;
  className?: string;
}

/** Unstyled citation chip with hover card. Consumers supply CSS. */
export function CitationChip({ number, excerpt, url, title, className }: CitationChipProps) {
  return (
    <span className={className} style={{ position: "relative", display: "inline-block" }}>
      <button
        type="button"
        aria-label={`Citation ${number}`}
        style={{
          fontSize: "0.75em",
          verticalAlign: "super",
          cursor: "pointer",
          border: "none",
          background: "transparent",
          color: "inherit",
          textDecoration: "underline",
        }}
      >
        [{number}]
      </button>
      {(excerpt || url) && (
        <span
          role="tooltip"
          style={{
            display: "none",
            position: "absolute",
            insetInlineStart: 0,
            top: "100%",
            zIndex: 20,
            minWidth: 220,
            maxWidth: 320,
            padding: 8,
            background: "var(--gw-popover-bg, #fff)",
            color: "var(--gw-popover-fg, #111)",
            border: "1px solid var(--gw-border, #ddd)",
            boxShadow: "0 4px 16px rgba(0,0,0,.08)",
          }}
          className="gw-cite-hover"
        >
          {title && <strong style={{ display: "block", marginBottom: 4 }}>{title}</strong>}
          {excerpt && <span style={{ display: "block", fontSize: 12 }}>{excerpt}</span>}
          {url && (
            <a href={url} style={{ fontSize: 11, display: "block", marginTop: 6 }}>
              {url}
            </a>
          )}
        </span>
      )}
      <style>{`.gw-cite-hover-parent:hover .gw-cite-hover, span:hover > .gw-cite-hover { display: block !important; }`}</style>
    </span>
  );
}

export interface SourceItem {
  id: number;
  url: string;
  title: string;
  snippet: string;
  domain: string;
  favicon?: string | null;
  published_at?: string | null;
  used_in_answer?: boolean;
}

export interface SourcesListProps {
  sources: SourceItem[];
  className?: string;
  style?: CSSProperties;
  usedLabel?: string;
}

/** Unstyled Google-style sources list. */
export function SourcesList({ sources, className, style, usedLabel = "Used in answer" }: SourcesListProps) {
  return (
    <ul className={className} style={{ listStyle: "none", padding: 0, margin: 0, ...style }}>
      {sources.map((s) => (
        <li key={s.id} style={{ marginBlockEnd: 16 }}>
          <a href={s.url} style={{ textDecoration: "none", color: "inherit" }}>
            <div style={{ display: "flex", gap: 8, alignItems: "center", fontSize: 12, opacity: 0.7 }}>
              {s.favicon ? <img src={s.favicon} alt="" width={14} height={14} /> : null}
              <span>{s.domain}</span>
              {s.published_at ? <span>· {s.published_at}</span> : null}
              {s.used_in_answer ? <span style={{ color: "var(--gw-accent, #2563eb)" }}>{usedLabel}</span> : null}
            </div>
            <div style={{ fontSize: 16, color: "var(--gw-link, #1a0dab)" }}>{s.title}</div>
            <div style={{ fontSize: 13, opacity: 0.85 }}>{s.snippet}</div>
          </a>
        </li>
      ))}
    </ul>
  );
}

export function HoverCard({ children, content }: { children: ReactNode; content: ReactNode }) {
  return (
    <span style={{ position: "relative", display: "inline-block" }}>
      {children}
      <span
        style={{
          display: "none",
          position: "absolute",
          zIndex: 30,
          insetInlineStart: 0,
          top: "100%",
          padding: 8,
          background: "var(--gw-popover-bg, #fff)",
          border: "1px solid var(--gw-border, #ddd)",
        }}
        className="gw-hover-card"
      >
        {content}
      </span>
      <style>{`span:hover > .gw-hover-card { display: block !important; }`}</style>
    </span>
  );
}
