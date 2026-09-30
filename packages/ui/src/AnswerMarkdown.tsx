// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 Ved Buddaraju

import type { Citation, SourceView } from "@gleanwise/client";
import { Children, isValidElement, memo, useMemo, useState, type ComponentProps, type ReactNode } from "react";
import Markdown from "react-markdown";
import rehypeHighlight from "rehype-highlight";
import rehypeKatex from "rehype-katex";
import remarkGfm from "remark-gfm";
import remarkMath from "remark-math";
import { CitationChip, type CitationInfo } from "./CitationChip";
import { useLabels } from "./labels";
import { remarkCitations } from "./remark-citations";
import { normalizeMath, safeUrl, splitBlocks, textOf } from "./text";

export interface AnswerMarkdownProps {
  text: string;
  sources?: SourceView[];
  citations?: Citation[];
  /** Map a remote image URL to something the browser may load (use `client.imageUrl`). Without it, images are not loaded at all. */
  resolveImage?(src: string): string;
  resolveAsset?(path: string): string;
  onOpenSource?(info: CitationInfo): void;
  className?: string;
}

const remarkPlugins = [remarkGfm, [remarkMath, { singleDollarTextMath: false }]] as never;
const rehypePlugins = [
  [rehypeKatex, { throwOnError: false, strict: "ignore" }],
  [rehypeHighlight, { detect: false, ignoreMissing: true }],
] as never;

function CopyButton({ text }: { text: string }) {
  const t = useLabels();
  const [done, setDone] = useState(false);
  return (
    <button
      type="button"
      className="gw-copy"
      data-done={done || undefined}
      onClick={() => {
        void navigator.clipboard?.writeText(text).then(() => {
          setDone(true);
          window.setTimeout(() => setDone(false), 1600);
        });
      }}
    >
      <span aria-live="polite">{done ? t.copied : t.copy}</span>
    </button>
  );
}

function CodeBlock({ children }: { children?: ReactNode }) {
  const code = Children.toArray(children).find(isValidElement) as
    { props: { className?: string; children?: ReactNode } } | undefined;
  const lang = /language-([\w+-]+)/.exec(code?.props.className ?? "")?.[1];
  return (
    <div className="gw-code" data-gw="code">
      <div className="gw-code-bar">
        <span className="gw-code-lang">{lang ?? ""}</span>
        <CopyButton text={textOf(code?.props.children).replace(/\n$/, "")} />
      </div>
      <pre tabIndex={0}>{children}</pre>
    </div>
  );
}

interface BlockProps extends Omit<AnswerMarkdownProps, "text" | "sources" | "citations" | "className"> {
  md: string;
  known: ReadonlySet<number>;
  info: ReadonlyMap<number, CitationInfo>;
}

const Block = memo(function Block({ md, known, info, resolveImage, onOpenSource }: BlockProps) {
  const t = useLabels();
  const plugins = useMemo(() => [...(remarkPlugins as unknown[]), remarkCitations(known)] as never, [known]);
  const components = useMemo(
    () =>
      ({
        "gw-cite": ({ n }: { n?: string }) => {
          const i = info.get(Number(n));
          return i ? <CitationChip info={i} onOpen={onOpenSource} /> : <>[{n}]</>;
        },
        a: ({ href, children }: ComponentProps<"a">) => {
          const safe = href ? (safeUrl(href) ?? (href.startsWith("mailto:") ? href : null)) : null;
          return safe ? (
            <a href={safe} rel="noopener noreferrer">
              {children}
            </a>
          ) : (
            <>{children}</>
          );
        },
        img: ({ src, alt }: ComponentProps<"img">) => {
          const ok = typeof src === "string" && safeUrl(src) && resolveImage;
          return ok ? (
            <img
              className="gw-image"
              src={resolveImage(src)}
              alt={alt ?? ""}
              loading="lazy"
              referrerPolicy="no-referrer"
            />
          ) : (
            <span className="gw-image-blocked">{alt || t.imageBlocked}</span>
          );
        },
        pre: ({ children }: ComponentProps<"pre">) => <CodeBlock>{children}</CodeBlock>,
        table: ({ children }: ComponentProps<"table">) => (
          <div className="gw-table" tabIndex={0} role="region" aria-label="Table">
            <table>{children}</table>
          </div>
        ),
      }) as never,
    [info, onOpenSource, resolveImage, t.imageBlocked],
  );
  return (
    <Markdown remarkPlugins={plugins} rehypePlugins={rehypePlugins} components={components}>
      {md}
    </Markdown>
  );
});

/**
 * Renders an answer as Markdown (GFM tables, highlighted code with copy, KaTeX math) with `[n]` markers
 * turned into citation chips. Finished blocks are memoised, so streaming stays cheap on long answers.
 */
export function AnswerMarkdown({
  text,
  sources = [],
  citations = [],
  resolveImage,
  resolveAsset = (p) => p,
  onOpenSource,
  className,
}: AnswerMarkdownProps) {
  const info = useMemo(() => {
    const m = new Map<number, CitationInfo>();
    for (const s of sources)
      m.set(s.id, {
        number: s.id,
        url: s.url,
        title: s.title,
        domain: s.domain,
        excerpt: s.snippet,
        favicon: s.favicon ? resolveAsset(s.favicon) : undefined,
      });
    for (const c of citations) {
      const base = m.get(c.number);
      m.set(c.number, {
        ...base,
        number: c.number,
        url: c.url,
        title: c.title || base?.title || "",
        excerpt: c.excerpt || base?.excerpt,
        domain: base?.domain,
        favicon: base?.favicon,
      });
    }
    return m;
  }, [sources, citations, resolveAsset]);
  const known = useMemo(() => new Set(info.keys()), [info]);
  const blocks = useMemo(() => splitBlocks(normalizeMath(text)), [text]);
  return (
    <div className={className ?? "gw-answer"} data-gw="answer">
      {blocks.map((b, i) => (
        <Block key={i} md={b} known={known} info={info} resolveImage={resolveImage} onOpenSource={onOpenSource} />
      ))}
    </div>
  );
}
