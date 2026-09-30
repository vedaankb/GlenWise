# GleanWise: Architecture

Open-source, bring-your-own-key / bring-your-own-model answer engine modeled on the publicly described architecture of Perplexity: live search, page fetch and parse, sub-document chunking, hybrid retrieval with multi-stage ranking, and cited answers.

Perplexity's internals are proprietary. This design follows what they have published (hybrid lexical + semantic retrieval, multi-stage ranking, dynamic parsing, sub-document retrieval) and adapts it to a system with no proprietary web index.

## 1. Goals and non-goals

Goals
- Local-first: install once, and it runs in the browser from then on with no per-use scripts.
- Headless: the core is usable by anyone building their own branded search service.
- BYOK / BYOM: any LLM or embedding model via LiteLLM, including local Ollama.
- Fast first paint: sources and a snippet-based answer immediately, upgraded to a full-content RAG answer.
- Modular enough that anyone can self-host it as a server.

Non-goals
- We do not host it. No hosted service, no built-in accounts, no per-user key vault, no billing.
- We do not run our own crawler or web index. Search comes from SearXNG.

## 2. Stack

| Layer | Choice |
|---|---|
| Backend | Python, FastAPI |
| LLM / embedding gateway | LiteLLM |
| Search | Self-hosted SearXNG (JSON API) |
| Frontend | Vite + React 19 (static build served by the core) |
| Client packages | TypeScript SDK, React hooks, unstyled component primitives |
| Streaming | SSE; cancel via a separate endpoint |
| Local storage | SQLite + FTS5 + sqlite-vec |
| Server-profile storage | Postgres + pgvector + ParadeDB pg_search (BM25) |
| Job runner | asyncio locally; arq + Redis in the server profile |
| Browser fallback | Playwright, bundled with the core install |
| License | AGPL-3.0 |

## 3. Repository layout

```
apps/web                 Vite/React reference UI (built only on the public packages)
packages/client          generated TypeScript SDK
packages/react           headless React hooks (phased SSE state machine)
packages/ui              unstyled component primitives (chips, hover card, sources list)
packages/widget          drop-in embeddable web component
integrations/mcp         MCP server (search/answer as tools)
integrations/cli         CLI
services/core            FastAPI backend
  search/                SearXNG client, query fan-out, URL normalize + dedupe
  fetch/                 static fetcher, Playwright fallback, SSRF guard, robots
  parse/                 readability-style content extraction
  chunk/                 heading-aware segmentation
  embed/                 Embedder interface (local + LiteLLM)
  index/                 Store interface (SQLite/sqlite-vec, Postgres/pgvector)
  retrieve/              BM25 + dense retrieval, RRF fusion
  rank/                  cross-encoder reranker
  llm/                   LiteLLM wrapper, prompts, citation assembly
  pipeline/              orchestration: Quick / Pro / Deep
  jobs/                  JobQueue interface (asyncio, arq)
  threads/               conversation state, query rewriting
  api/                   HTTP + SSE endpoints, OpenAI-compatible endpoint, operator endpoints
deploy/                  installer, service definitions, compose files (alternative, server profile)
scripts/                 optional benchmark runner
```

## 4. Deployment profiles

Out of the box (default): the user clones the repo and runs the install script once. The installer creates the Python environment, installs dependencies (including Playwright's Chromium), builds the frontend, sets up SearXNG, and registers a background service that starts at login (launchd, systemd user unit, or Windows Task Scheduler). After that the user just opens GleanWise in the browser. No script is run per use. The UI is installable as a PWA, and can optionally register as a browser default search engine. SQLite file, asyncio job runner, single user, no auth.

Windows: a single signed `.exe` installer. It enables WSL2 (possibly one reboot; CPU virtualization must be on), imports a bundled Linux distro the user never sees, runs SearXNG and the core inside it, registers everything to start at login, and opens the browser or PWA. The documented Docker path is the fallback.

Docker compose (alternative): the same services under compose with a restart policy, for people who prefer containers.

Server profile (for operators who want to host it themselves): adds `postgres` (pgvector + pg_search) and `redis` (arq worker). We ship the profile and the seams below; operators supply auth, tenancy and key management. We do not host it.

Seams left open for operators
- An auth middleware interface, defaulting to none.
- A schema that carries a nullable `user_id` on threads, messages and chunks.
- Server-side keys via env or config.

## 5. Request lifecycle

Endpoints
- `POST /query` returns `query_id` (accepts `thread_id`, `mode`).
- `GET /stream/{query_id}` streams SSE.
- `POST /cancel/{query_id}` cancels a running query.

Phased pipeline
1. **Rewrite / plan.** Rewrite the query using thread history, then decompose into sub-queries (depth depends on mode, section 6).
2. **Search.** Query SearXNG in parallel per sub-query. Normalize URLs, dedupe.
3. **Phase 1 (fast, Quick mode only).** Emit sources, then stream a snippet-based answer with numbered citations. Pro and Deep skip this phase and wait for the full answer.
4. **Fetch.** Concurrently fetch top results. Static fetch, then readability-style parse. If the result is empty or thin, fall back to Playwright.
5. **Segment.** Heading-aware chunks, up to ~400 tokens, small overlap. Each chunk keeps URL, heading path, and offsets.
6. **BM25 prune.** Lexical scoring over the fresh chunks to cut the set.
7. **Inline embed.** Embed only the survivors, in the request path.
8. **Retrieve + rank.** BM25 and dense retrieval, RRF fusion, local cross-encoder rerank.
9. **Phase 2 (upgrade).** Full-content RAG answer replaces the fast answer in place with a subtle "upgraded" indicator. Citations map to chunk IDs.
10. **Background.** Remaining chunks are embedded and cached by the job runner.

Proposed SSE event types (names are a proposal): `plan`, `sources`, `answer_delta`, `answer_upgrade`, `reasoning_delta` and `visit` (Deep), `done`, `error`.

## 6. Modes

- **Quick.** Single-pass rewrite and decomposition, then the phased pipeline above.
- **Pro.** For regular users asking questions that need reading into websites. A single deeper pass: fetch and read the top pages once, no loop, then answer from full content. No snippet-first phase.
- **Deep.** A high-end research mode with no limits. It recurses with the model until no problems are left in the answer: search, partial synthesis, critique for gaps or unsupported claims, re-search, repeat. Reasoning and visited sites are streamed to the UI while it runs. The recursion stops when the critic finds no unresolved issues. Cancel is always available, and stall detection ends the loop if consecutive iterations add nothing new. No snippet-first phase; the answer appears when research is done.

## 7. Search (SearXNG)

- Runs as a managed background process started by the core (or as a compose service). JSON output must be enabled in its `settings.yml`.
- Upstream engines rate-limit or block; expect engine tuning and retries.
- Results are normalized and deduped by canonical URL before fetching.

## 8. Fetch and parse

Defaults, all on:
- SSRF protection: block private, loopback and link-local ranges, and re-check on every redirect.
- robots.txt respected.
- Size and time caps on every fetch.

Parsing: readability-style boilerplate and navigation stripping, with Playwright for JS-heavy or empty pages. Extraction is behind an interface so parsers can be swapped later.

## 9. Storage

Store interface with two backends. Sketch:

```
docs      url, canonical_url, content_type, etag, last_modified, fetched_at, ttl_class
chunks    id, doc_id, heading_path, text, start, end,
          embedding_model, dim, embedding
threads   id, user_id?, created_at
messages  id, thread_id, role, content, citations, mode
```

- Local: FTS5 index for BM25, sqlite-vec for vectors.
- Server profile: ParadeDB pg_search for true BM25, pgvector for vectors.
- Every vector records the embedding model and dimension. Changing model triggers a re-embed job.

## 10. Retrieval and ranking

1. BM25 and dense retrieval over cached chunks.
2. Reciprocal rank fusion into one candidate set.
3. Local cross-encoder rerank.

## 11. Models

- LLM: any LiteLLM model string, overridable per request. No default model. First-run setup asks for provider, model and key, or an Ollama endpoint. Config and env override the UI.
- Embedder: local by default (fastembed/ONNX, bge-small class, English). Any LiteLLM embedding model is selectable. A multilingual profile (e.g. bge-m3 with a multilingual reranker) is opt-in.
- Reranker: local cross-encoder, English small by default; multilingual in the opt-in profile.

## 12. Background jobs

`JobQueue` interface. Local: asyncio tasks. Server profile: arq with Redis. Jobs: embed long-tail chunks, cache warming, re-embed on model change, freshness revalidation, retention purge (see section 19).

## 13. Threads

Threads carry full conversation context. Each follow-up is rewritten from history into a standalone query before searching.

## 14. Citations and UI

Full UX and UI decisions live in `UX_UI.md`.

- Numbered inline chips in the answer, with a hover card showing the source excerpt.
- A right-hand rail of Google-style result links, with a badge on sources the answer cited.
- Deep mode uses a dedicated research view streaming reasoning and visited sites.

## 15. Cache and freshness

- TTL by content type (short for news, long for documentation).
- Conditional GET (ETag / Last-Modified) revalidation on expiry.

## 16. Evaluation

Optional script that runs an existing open benchmark (FRAMES-style) against the pipeline. Not part of the default install.

## 17. Headless layer and integration surfaces

The core is headless. The out-of-box UI is a reference client that uses only the public packages, no private APIs.

Public layers
- HTTP + SSE API with an OpenAPI spec.
- `packages/client`: generated TypeScript SDK.
- `packages/react`: headless hooks wrapping the phased SSE stream (sources, snippet answer, upgrade, Deep events).
- `packages/ui`: unstyled primitives (citation chips, hover card, sources list).

Extra surfaces, all in v1
- OpenAI-compatible `/chat/completions` endpoint returning citations. Modes map to model names (`gleanwise-quick`, `gleanwise-pro`, `gleanwise-deep`); focus scope is passed via an extension field.
- MCP server with four tools: `search` (ranked results), `answer` (Quick/Pro/Deep with citations), `fetch_page` (parsed content of a URL, SSRF-guarded), `retrieve` (query the local chunk index).
- Drop-in embeddable web component.
- CLI.

## 18. Operator endpoints

For people who host it and want to collect signal or fine-tune. Nothing is sent anywhere by default; locally, thumbs have no effect.
- Feedback events (thumb + optional comment).
- Full trace export as JSONL (query, sub-queries, retrieved chunks, answer, citations).
- Operational metrics (latency, cost, errors) in Prometheus format.
- Webhook push to an operator-configured URL.

## 19. Thread retention

Threads are deleted after 28 days by default. Retention is configurable. Pinned threads are exempt from deletion.

## 20. Milestones

- M0: skeleton (SearXNG, core, web) and the install script with background service.
- M1: search and the snippet answer streaming end to end.
- M2: fetch, parse, chunk, Playwright fallback, SSRF guard.
- M3: index, BM25 prune, hybrid retrieval, rerank.
- M4: phase 2 upgrade; SDK, hooks, primitives; reference UI (see UX_UI.md).
- M5: background encoding, cache and TTL policy.
- M6: Pro mode, then Deep mode with the research view.
- M7: threads, query rewriting, retention, thread controls.
- M8: OpenAI-compatible endpoint, MCP server, CLI, embeddable widget.
- M9: operator endpoints (feedback, traces, metrics, webhook).
- M10: server profile (Postgres/ParadeDB, Redis/arq, auth seam).
- M11: benchmark script.

## 21. Open items to confirm

- None. All open items are resolved. Deep mode exports a research summary in the standard thread export, plus a separate full-log export (see `UX_UI.md`).
