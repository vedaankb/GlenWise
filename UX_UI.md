# GleanWise: UX and UI

Decisions for the out-of-box reference UI and the headless packages behind it. Architecture lives in `ARCHITECTURE.md`.

## 1. Principles

- The core is headless. The out-of-box app is a reference client, built only on the public SDK, hooks and primitives. It uses no private APIs.
- Anyone building their own search service can reuse the core and packages with their own branding.
- Clean, minimal, neutral look (Perplexity-like). No cat or paw branding in the reference UI.
- The app runs in the browser after a one-time install. It starts at login as a background service, installs as a PWA, and can register as a browser default search engine.

## 2. App shell

Left sidebar
- New search button.
- Past threads for 28 days (retention is configurable, default 28 days with deletion). Pinned threads are exempt from deletion.
- Thread controls: rename, delete, pin, search past threads.

Search box (home and follow-ups)
- Mode control: segmented Quick / Pro / Deep.
- Focus modes: General web (default), Academic / papers, News, Social / forums (mapped to SearXNG categories).

Home screen: search box with the sidebar. No suggested queries or dashboard.

## 3. Answer page

Layout: two columns.
- Left, about 2/3: the generated answer with numbered citation chips. Chips open a hover card with the source excerpt.
- Right, about 1/3: a Google-style list of relevant result links. Each row shows favicon, title, domain, snippet, publish date or freshness, and a "used in answer" badge for sources the answer cited.
- Clicking a result navigates in the same tab. Browser back must return to the thread with scroll position and state restored.

Thread view: turns stack in one scrolling thread with a sticky follow-up box at the bottom. Follow-up context carries over via query rewriting from history.

Loading and streaming
- A live step indicator (Searching, Reading, Writing) with streamed text.
- Quick mode only: the snippet answer is replaced in place by the full-content answer, with a subtle "upgraded" indicator. Pro waits for the full answer, showing the step indicator meanwhile.

## 4. Deep mode

A dedicated research view showing the steps and a browsing log (reasoning and visited sites, streamed live). The answer appears when the research is done.

Export: the standard thread export includes a summary of the research, and a separate export provides the full log (steps and visited sites).

## 5. Per-answer actions

- Copy as markdown.
- Export thread (markdown and PDF).
- Regenerate, or rerun in another mode or model.
- Feedback thumbs. Stored locally, with no local effect. They feed the operator endpoints described in `ARCHITECTURE.md`. Nothing is sent anywhere by default.

## 6. Setup, settings and failures

- Guided first-run wizard: LLM provider/model/key (or Ollama endpoint), embedder, health checks. Then a full settings page. Config and env override the UI.
- Failures are shown as inline actionable errors (bad key, blocked engines, fetch failures), plus a diagnostics page with SearXNG, LLM and embedder health.

## 7. Responsive, keyboard, accessibility, i18n

- Fully responsive: the sidebar becomes a drawer and the right rail stacks below the answer on small screens.
- Keyboard shortcuts for new thread, focus search and switch mode.
- WCAG AA target.
- Full i18n from day one, including RTL. First release ships English and Arabic (to validate RTL); other locales are community-contributed. Implication: use logical CSS properties (start/end instead of left/right) and direction-aware icons throughout, and externalize all strings.

## 8. UI foundation and theming

- Tailwind + Radix primitives (shadcn-style).
- Light and dark themes, following the OS preference by default with a user override, plus a user-selectable accent color.
- Design tokens exposed as CSS variables so integrators can rebrand by overriding tokens.

## 9. Answer renderer

- Markdown with GFM tables.
- Code blocks with syntax highlighting and a copy button.
- Math rendering (KaTeX).
- Image and video results shown in the answer. Images and thumbnails are proxied through core (no hotlink leaks, SSRF-guarded).

## 10. Headless packages and surfaces

- `packages/client`: generated TypeScript SDK.
- `packages/react`: headless hooks (state machine for the phased SSE stream, including Deep events).
- `packages/ui`: unstyled primitives (citation chips, hover card, sources list).
- `packages/widget`: drop-in embeddable web component.
- OpenAI-compatible `/chat/completions` endpoint with citations, MCP server, and CLI. All in v1.

## 11. Open items to confirm

- None. All open items are resolved.
