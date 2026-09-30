# GleanWise

An open-source, bring-your-own-key answer engine. It searches the web through a private SearXNG, reads the pages, ranks the passages that matter, and writes an answer with numbered citations, using whichever language model you choose. Your questions, history and keys stay on your machine.

Design docs: [ARCHITECTURE.md](ARCHITECTURE.md) · [UX_UI.md](UX_UI.md) · [PRIVACY.md](PRIVACY.md) · [PRIVACY_DECISIONS.md](PRIVACY_DECISIONS.md)

## Install

**macOS / Linux, no Docker**

```bash
./deploy/install.sh
```

This sets up the Python environment, installs a private SearXNG, downloads the small local search models, and starts the service at login (launchd or a systemd user service). Open http://127.0.0.1:8787 and the setup guide asks for a model and key, and tests them before saving.

Remove it with `./deploy/install.sh --uninstall` (your data is kept) or `--uninstall --purge` (everything is deleted). Check on it any time with `gleanwise doctor`.

**Docker (any OS, including Windows)**

```bash
cd deploy/compose
cp ../../.env.example .env         # set SEARXNG_SECRET: openssl rand -hex 32
docker compose up -d --build
```

Windows notes are in [deploy/windows](deploy/windows/README.md).

## Modes

- **Quick**: a fast draft from search snippets, replaced in place by a full-page answer.
- **Pro**: reads the top pages first, then answers.
- **Deep**: plans several searches, reads across rounds, and shows its research log. Export the log separately from the answer.

Focus (General, Academic, News, Social) changes where it looks. Answers can be copied as Markdown, exported as Markdown or PDF, regenerated in another mode, and rated.

## Use it from your own code

The web app is one client of a public API. Everything it does is available to you.

| Package                   | What it is                                                              |
| ------------------------- | ----------------------------------------------------------------------- |
| `packages/client`         | TypeScript SDK: typed requests, resumable streaming, shared answer state |
| `packages/react`          | `useAnswer` and friends for your own React UI                            |
| `packages/ui`             | Unstyled primitives: Markdown renderer, citation chips, source list      |
| `packages/widget`         | `<gleanwise-search>` web component to embed search on any site               |
| `integrations/cli`        | `gleanwise ask "…"` in the terminal                                           |
| `integrations/mcp`        | MCP server exposing search, answer, page fetch and retrieval             |
| `services/core`           | The FastAPI service (OpenAPI at `/docs`)                                |

```bash
# CLI
pnpm build && node integrations/cli/dist/index.js ask "What is BM25?" --mode quick

# Any OpenAI-compatible client
curl http://127.0.0.1:8787/v1/chat/completions -H 'content-type: application/json' \
  -d '{"model":"gleanwise-quick","messages":[{"role":"user","content":"Hello"}]}'

# MCP
node integrations/mcp/dist/index.js
```

Embedding the widget on another site needs that site listed in `GLEANWISE_ALLOWED_ORIGINS`, and an API token if the instance is shared.

## Development

```bash
pnpm install
(cd services/core && uv sync --extra dev --extra server)

pnpm dev:stack     # fake web, search and model on fixed ports; no keys or network needed
pnpm dev           # the web app with hot reload (proxies the API on :8787)

pnpm build && pnpm typecheck && pnpm lint && pnpm test    # everything CI runs, JS side
cd services/core && uv run ruff check . && uv run mypy gleanwise && uv run pytest -q
pnpm gen:api       # after changing the API: refreshes openapi.json and the SDK types
```

`pnpm dev:stack --unconfigured` starts with no model so you can walk through the first-run guide.

## Sharing one instance

`deploy/compose/docker-compose.server.yml` runs the core with Postgres + pgvector and refuses to start without `GLEANWISE_API_TOKEN`, `GLEANWISE_ALLOWED_HOSTS`, `SEARXNG_SECRET` and `POSTGRES_PASSWORD`. Put a TLS-terminating reverse proxy in front of it. There is one shared token, not per-user accounts.

## Known limits

Honest edges of this release:

- **One core process.** Live answer streams are held in that process's memory. Several replicas need sticky routing on the query id; there is no Redis job queue.
- **Failed or stopped answers are not saved.** A thread keeps only completed answers (a stopped answer stays visible until you leave the page).
- **Postgres search is plain full-text plus pgvector.** BM25 ranking through ParadeDB is not implemented.
- **SSRF protection for the optional headless browser is best effort.** The plain fetcher pins resolved addresses; pages rendered in Chromium can issue their own requests. Leave `--with-browser` off on shared servers.
- **Chinese, Japanese and Korean keyword matching is weak.** Semantic (embedding) retrieval still works.
- **Verified on:** macOS (installer, launchd template linted but not loaded), Docker Linux images (both compose files), SQLite and Postgres 16 with pgvector. The systemd unit and Windows routes are untested.

## License

GleanWise is licensed under **AGPL-3.0-or-later**. See [LICENSE](LICENSE).
Anyone who offers a modified version of GleanWise over a network must make the
corresponding source available to its users under the AGPL.

Organizations that cannot meet those network-source obligations may request a
separate commercial license ([COMMERCIAL-LICENSE.md](COMMERCIAL-LICENSE.md)).
A share of commercial license revenue is pledged to contributors
([REVENUE-SHARING.md](REVENUE-SHARING.md)). Contributions require a signed
[CLA](CLA.md); see [CONTRIBUTING.md](CONTRIBUTING.md).
