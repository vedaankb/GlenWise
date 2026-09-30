// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 Ved Buddaraju

import type { SourceView } from "@gleanwise/client";
import type { ReactNode } from "react";
import { useLabels } from "./labels";
import { relativeTime, safeUrl } from "./text";

export interface SourceListProps {
  sources: SourceView[];
  locale?: string;
  /** Turn the server's relative favicon path into a loadable URL. */
  resolveAsset?(path: string): string;
  onOpen?(source: SourceView): void;
  /** Drop sources that could not be opened. Default true. */
  hideFailed?: boolean;
  renderRow?(source: SourceView, defaults: { favicon: ReactNode }): ReactNode;
  className?: string;
}

/** A Google-style results list: favicon, title, domain, freshness, snippet, and a "used in answer" mark. */
export function SourceList({
  sources,
  locale,
  resolveAsset = (p) => p,
  onOpen,
  hideFailed = true,
  renderRow,
  className,
}: SourceListProps) {
  const t = useLabels();
  const rows = hideFailed ? sources.filter((s) => s.state !== "failed") : sources;
  return (
    <ol className={className ?? "gw-sources"} data-gw="sources">
      {rows.map((s) => {
        const href = safeUrl(s.url);
        const when = relativeTime(s.published_at, locale);
        const favicon = s.favicon ? (
          <img
            className="gw-source-favicon"
            src={resolveAsset(s.favicon)}
            alt=""
            width={16}
            height={16}
            loading="lazy"
          />
        ) : (
          <span className="gw-source-favicon" aria-hidden="true" />
        );
        return (
          <li
            key={s.id}
            className="gw-source"
            id={`source-${s.id}`}
            data-state={s.state}
            data-used={s.used_in_answer || undefined}
          >
            {renderRow ? (
              renderRow(s, { favicon })
            ) : (
              <>
                <div className="gw-source-meta">
                  <span className="gw-source-number">{s.id}</span>
                  {favicon}
                  <span className="gw-source-domain">{s.domain}</span>
                  {when ? <span className="gw-source-date">· {when}</span> : null}
                </div>
                {href ? (
                  <a className="gw-source-title" href={href} onClick={() => onOpen?.(s)}>
                    {s.title || s.domain || s.url}
                  </a>
                ) : (
                  <span className="gw-source-title">{s.title || s.url}</span>
                )}
                {s.snippet ? <p className="gw-source-snippet">{s.snippet}</p> : null}
                <div className="gw-source-flags">
                  {s.used_in_answer ? (
                    <span className="gw-badge" data-kind="used">
                      {t.usedInAnswer}
                    </span>
                  ) : null}
                  {s.state === "reading" ? (
                    <span className="gw-badge" data-kind="reading">
                      {t.reading}
                    </span>
                  ) : null}
                  {s.state === "failed" ? (
                    <span className="gw-badge" data-kind="failed" title={s.reason ?? undefined}>
                      {t.failed}
                    </span>
                  ) : null}
                  {s.state === "skipped" ? (
                    <span className="gw-badge" data-kind="skipped" title={s.reason ?? undefined}>
                      {t.skipped}
                    </span>
                  ) : null}
                </div>
              </>
            )}
          </li>
        );
      })}
    </ol>
  );
}
