// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 Ved Buddaraju

import {
  GleanWiseClient,
  GleanWiseError,
  describePhase,
  reduce,
  startState,
  type AnswerState,
  type Focus,
  type Mode,
  type QueryHandle,
} from "@gleanwise/client";

/**
 * <gleanwise-search api="http://127.0.0.1:8787" mode="quick" focus="general" token="…" placeholder="…"></gleanwise-search>
 *
 * Every piece of remote text (answers, titles, URLs) reaches the DOM only through textContent and
 * validated href values — never innerHTML — so a hostile web page cannot inject markup or script.
 * Style it from outside with CSS variables: --gw-accent, --gw-fg, --gw-bg, --gw-border, --gw-radius.
 */
const STYLE = `
:host { display: block; font: 15px/1.55 system-ui, -apple-system, "Segoe UI", sans-serif; color: var(--gw-fg, #16181d); }
* { box-sizing: border-box; }
form { display: flex; gap: .5rem; }
input, select { font: inherit; color: inherit; background: var(--gw-bg, #fff); border: 1px solid var(--gw-border, #d5d8de); border-radius: var(--gw-radius, 10px); padding: .6rem .8rem; }
input { flex: 1; min-inline-size: 0; }
input:focus-visible, button:focus-visible, a:focus-visible, select:focus-visible { outline: 2px solid var(--gw-accent, #3b5bdb); outline-offset: 2px; }
button { font: inherit; cursor: pointer; border: 0; border-radius: var(--gw-radius, 10px); padding: .6rem 1rem; background: var(--gw-accent, #3b5bdb); color: #fff; }
button.secondary { background: transparent; color: inherit; border: 1px solid var(--gw-border, #d5d8de); }
button[disabled] { opacity: .55; cursor: default; }
.status { margin-block-start: .75rem; font-size: 13px; opacity: .7; min-block-size: 1.2em; }
.answer { margin-block-start: .5rem; }
.answer p { margin: 0 0 .75em; }
.answer ul { margin: 0 0 .75em; padding-inline-start: 1.25em; }
.answer.draft { opacity: .75; }
.answer code { font-family: ui-monospace, monospace; font-size: .9em; background: rgba(127,127,127,.15); padding: .1em .35em; border-radius: 4px; }
a.cite { text-decoration: none; font-size: .75em; vertical-align: super; padding: 0 .15em; color: var(--gw-accent, #3b5bdb); font-weight: 600; }
.sources { margin: 1rem 0 0; padding: 0; list-style: none; display: grid; gap: .5rem; }
.sources li { font-size: 13px; }
.sources a { color: inherit; font-weight: 600; text-decoration: none; }
.sources a:hover { text-decoration: underline; }
.sources .dom { opacity: .65; display: block; }
.error { margin-block-start: .75rem; padding: .75rem .9rem; border-radius: var(--gw-radius, 10px); background: rgba(224, 49, 49, .09); border: 1px solid rgba(224, 49, 49, .35); }
.error strong { display: block; }
.sr { position: absolute; inline-size: 1px; block-size: 1px; overflow: hidden; clip-path: inset(50%); white-space: nowrap; }
`;

function h<K extends keyof HTMLElementTagNameMap>(
  tag: K,
  props: Record<string, string> = {},
  ...kids: (Node | string)[]
): HTMLElementTagNameMap[K] {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(props)) el.setAttribute(k, v);
  for (const k of kids) el.append(k);
  return el;
}

/** Only http(s) links are ever made clickable. */
export function safeHref(raw: string): string | null {
  try {
    const u = new URL(raw);
    return u.protocol === "http:" || u.protocol === "https:" ? u.href : null;
  } catch {
    return null;
  }
}

/** Minimal, safe Markdown → DOM: paragraphs, bullet lists, **bold**, `code`, and [n] citations. */
export function renderAnswer(text: string, urlFor: (n: number) => string | null): DocumentFragment {
  const frag = document.createDocumentFragment();
  const inline = (parent: Element | DocumentFragment, s: string) => {
    const re = /(\*\*[^*]+\*\*|`[^`]+`|\[(\d{1,3})\])/g;
    let last = 0;
    for (const m of s.matchAll(re)) {
      if (m.index! > last) parent.append(s.slice(last, m.index));
      const tok = m[0];
      if (tok.startsWith("**")) parent.append(h("strong", {}, tok.slice(2, -2)));
      else if (tok.startsWith("`")) parent.append(h("code", {}, tok.slice(1, -1)));
      else {
        const n = Number(m[2]);
        const href = urlFor(n);
        parent.append(
          href
            ? h(
                "a",
                { class: "cite", href, target: "_blank", rel: "noopener noreferrer", "aria-label": `Source ${n}` },
                String(n),
              )
            : tok,
        );
      }
      last = m.index! + tok.length;
    }
    if (last < s.length) parent.append(s.slice(last));
  };
  let list: HTMLUListElement | null = null;
  for (const block of text.split(/\n{2,}/)) {
    for (const line of block.split("\n")) {
      const li = /^\s*[-*]\s+(.*)$/.exec(line);
      if (li) {
        if (!list) frag.append((list = h("ul")));
        const item = h("li");
        inline(item, li[1]);
        list.append(item);
      } else if (line.trim()) {
        list = null;
        const heading = /^#{1,6}\s+(.*)$/.exec(line);
        const p = heading ? h("p", {}, h("strong")) : h("p");
        inline(heading ? (p.firstChild as Element) : p, heading ? heading[1] : line);
        frag.append(p);
      }
    }
    list = null;
  }
  return frag;
}

export class GleanWiseSearchElement extends HTMLElement {
  static get observedAttributes() {
    return ["placeholder"];
  }

  private root = this.attachShadow({ mode: "open" });
  private input!: HTMLInputElement;
  private go!: HTMLButtonElement;
  private stopBtn!: HTMLButtonElement;
  private statusEl!: HTMLElement;
  private live!: HTMLElement;
  private out!: HTMLElement;
  private handle: QueryHandle | null = null;
  private abort: AbortController | null = null;

  connectedCallback() {
    if (this.input) return;
    this.input = h("input", {
      type: "search",
      name: "q",
      autocomplete: "off",
      "aria-label": this.getAttribute("label") ?? "Ask a question",
    });
    this.input.placeholder = this.getAttribute("placeholder") ?? "Ask anything…";
    this.go = h("button", { type: "submit" }, this.getAttribute("submit-label") ?? "Ask");
    this.stopBtn = h(
      "button",
      { type: "button", class: "secondary", hidden: "" },
      this.getAttribute("stop-label") ?? "Stop",
    );
    this.statusEl = h("div", { class: "status", "aria-hidden": "true" });
    this.live = h("div", { class: "sr", role: "status", "aria-live": "polite" });
    this.out = h("div", { "aria-busy": "false" });
    const form = h("form", { role: "search" }, this.input, this.go, this.stopBtn);
    form.addEventListener("submit", (e) => {
      e.preventDefault();
      void this.run();
    });
    this.stopBtn.addEventListener("click", () => void this.handle?.cancel().catch(() => undefined));
    this.root.append(h("style", {}, STYLE), form, this.statusEl, this.live, this.out);
    const initial = this.getAttribute("query");
    if (initial) {
      this.input.value = initial;
      void this.run();
    }
  }

  attributeChangedCallback(name: string, _old: string | null, value: string | null) {
    if (name === "placeholder" && this.input) this.input.placeholder = value ?? "Ask anything…";
  }

  disconnectedCallback() {
    this.abort?.abort();
  }

  private client(): GleanWiseClient {
    return new GleanWiseClient({
      baseUrl: this.getAttribute("api") ?? undefined,
      token: this.getAttribute("token") ?? undefined,
    });
  }

  private async run() {
    const query = this.input.value.trim();
    if (!query) return;
    this.abort?.abort();
    const ctl = (this.abort = new AbortController());
    this.busy(true);
    let state: AnswerState = startState();
    this.paint(state);
    try {
      this.handle = await this.client().query(
        {
          query,
          mode: (this.getAttribute("mode") ?? "quick") as Mode,
          focus: (this.getAttribute("focus") ?? "general") as Focus,
          persist: false,
        },
        { signal: ctl.signal },
      );
      for await (const ev of this.handle.events()) {
        state = reduce(state, ev);
        this.paint(state);
      }
    } catch (e) {
      if ((e as Error)?.name !== "AbortError")
        this.paint({
          ...state,
          phase: "error",
          error:
            e instanceof GleanWiseError
              ? e.toBody()
              : { code: "error", message: String(e instanceof Error ? e.message : e), retryable: true },
        });
    } finally {
      if (this.abort === ctl) this.busy(false);
    }
  }

  private busy(on: boolean) {
    this.go.disabled = on;
    this.stopBtn.hidden = !on;
    this.out.setAttribute("aria-busy", String(on));
  }

  private paint(s: AnswerState) {
    const urlFor = (n: number) => {
      const src = s.sources.find((x) => x.id === n);
      return src ? safeHref(src.url) : null;
    };
    const status = s.phase === "done" || s.phase === "error" ? "" : describePhase(s);
    this.statusEl.textContent = status;
    if (s.phase === "done") this.live.textContent = "Answer ready";
    else if (s.phase === "error") this.live.textContent = s.error?.message ?? "Something went wrong";
    else if (status && this.live.textContent !== status) this.live.textContent = status;

    const nodes: Node[] = [];
    if (s.answer) {
      const box = h("div", { class: s.draft ? "answer draft" : "answer" });
      box.append(renderAnswer(s.answer, urlFor));
      nodes.push(box);
    }
    if (s.error) {
      const box = h("div", { class: "error", role: "alert" }, h("strong", {}, s.error.message));
      if (s.error.hint) box.append(s.error.hint);
      nodes.push(box);
    }
    const shown = s.sources.filter((x) => safeHref(x.url) && x.state !== "failed");
    if (shown.length && s.phase !== "connecting") {
      const ul = h("ul", { class: "sources", "aria-label": "Sources" });
      for (const x of shown.slice(0, 8)) {
        const a = h(
          "a",
          { href: safeHref(x.url)!, target: "_blank", rel: "noopener noreferrer" },
          `[${x.id}] ${x.title || x.domain || x.url}`,
        );
        ul.append(h("li", {}, a, h("span", { class: "dom" }, x.domain)));
      }
      nodes.push(ul);
    }
    this.out.replaceChildren(...nodes);
  }
}

if (typeof customElements !== "undefined" && !customElements.get("gleanwise-search")) {
  customElements.define("gleanwise-search", GleanWiseSearchElement);
}
