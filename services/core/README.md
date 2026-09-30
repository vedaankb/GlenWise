# GleanWise core

FastAPI service: private SearXNG search, safe page fetching, parsing and chunking, hybrid retrieval (vectors + full-text + reranking), LiteLLM answers, resumable SSE streaming, and the web app itself (served from the same origin).

```bash
uv sync --extra dev --extra server
uv run gleanwise serve            # http://127.0.0.1:8787, API docs at /docs
uv run gleanwise doctor           # checks storage, search, model, embeddings and explains fixes
uv run gleanwise prefetch         # download local models now (for offline use)
uv run gleanwise token            # generate an API token
uv run gleanwise openapi out.json # write the OpenAPI schema

uv run ruff check . && uv run mypy gleanwise && uv run pytest -q
```

The web app is found in `GLEANWISE_WEB_DIR`, `gleanwise/web`, or `apps/web/dist` in a checkout. Configuration is documented in `../../.env.example`.
