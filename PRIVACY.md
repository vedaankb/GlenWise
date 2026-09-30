# GleanWise: Privacy threat model

What data exists, where it can go, who can touch it, and what we promise. Product decisions that produced this model live in [`PRIVACY_DECISIONS.md`](PRIVACY_DECISIONS.md).

```
                    ┌─────────────────────────────────────────┐
                    │              Your machine                │
  Browser UI ──────►│  GleanWise core (127.0.0.1)              │
  CLI / MCP  ──────►│    ├─ SQLite (threads, cache, vectors)  │
                    │    ├─ settings.json (secrets masked)    │
                    │    └─ managed SearXNG (loopback)        │
                    └───────────────┬─────────────────────────┘
                                    │ only when you ask
                    ┌───────────────▼─────────────────────────┐
                    │  Outbound via local egress gateway      │
                    │    → search engines (via SearXNG)       │
                    │    → page origins you cite              │
                    │    → your LLM / embed endpoint (BYOK)   │
                    │  (optional SOCKS5 / Tor for search/fetch)│
                    └─────────────────────────────────────────┘
```

We do **not** run accounts, analytics, update phoning-home, or a hosted backend. Nothing leaves until you search, test a connection, or (optionally) hit an operator export you turned on.

## 1. Assets

| Asset | Where it lives | Sensitivity |
|---|---|---|
| Questions, answers, citations | SQLite under the data dir; memory while streaming | High |
| Cached page text and vectors | Same DB / cache dir | High |
| BYOK API keys | `settings.json` (mode `0600`) or env; never returned by the API | Critical |
| Auth token | Env / settings when configured | Critical |
| Thumbs feedback, traces | Local DB only | Medium |
| Embed / rerank models | Data dir `models/` | Low (public weights) |

Data directory defaults to `~/.gleanwise` (installer) or `./data` (dev). Directory mode `0700`.

## 2. Trust boundaries

1. **Browser ↔ core.** Same origin when the UI is served by the core. Host allowlist and Origin checks stop other sites from reading the API (DNS rebinding / CSRF). Optional bearer token.
2. **Core ↔ SearXNG.** Loopback by default; operator-configured URL. Treated as trusted search infrastructure, not an open SSRF target. When GleanWise manages SearXNG itself, the child process is configured to send its upstream queries through the local egress gateway, so they appear in Diagnostics → Network activity and honour SOCKS5/Tor routing. **An external SearXNG (a compose service or your own instance) cannot be reconfigured by GleanWise**: its upstream traffic does not pass the gateway and is not logged here. The gateway records only the core → SearXNG hop for such setups.
3. **Core ↔ the public web.** Fetcher resolves DNS, pins the address, blocks private/link-local unless explicitly allowed for labs. Robots respected. Response size capped. Markdown images are re-fetched through the core so pages cannot track you via `<img>`.
4. **Core ↔ model provider.** Only the endpoint you configured (cloud or local). Keys never leave for any other host.
5. **Operator / shared host.** If someone else runs the server profile, they can read disk and memory. Encryption at rest and tenancy are theirs. A single shared API token is the shipped auth seam — not per-user accounts.

## 3. What leaves the machine (per user action)

| Action | Destinations | Payload |
|---|---|---|
| Ask a question | SearXNG → upstream engines; fetched page hosts; LLM API | Query (and rewritten variants); page GETs; prompt = query + retrieved passages |
| Test connection (setup / settings) | LLM base URL; SearXNG | Tiny probe prompt; health ping |
| Prefetch models | Hugging Face (or configured mirror) | Model file downloads |
| Open a citation | The source host (your browser, same tab) | Normal navigation |
| Thumbs / diagnostics | **Local only** | — |
| Webhook (if you set one) | Your URL | Signed JSON summary of a completed answer |
| Widget on a third-party site | Your core origin | Needs that origin in `GLEANWISE_ALLOWED_ORIGINS` |

No destination is ours. Strict Local removes the LLM / embed rows for non-loopback hosts. Tor / SOCKS5 changes the path, not the fact that search engines see a query.

## 4. Adversaries and mitigations

| Adversary | Goal | Mitigation |
|---|---|---|
| Malicious website | Hit `http://127.0.0.1:8787` via DNS rebinding or CSRF | Host allowlist; Origin check on mutating methods; optional bearer token; CSP `frame-ancestors 'none'` |
| Malicious or tracking page | Exfiltrate via fetched content or markdown images | SSRF pin; size caps; image proxy; Playwright tracker blocklist |
| Local malware / other OS users | Read DB or keys | `0700` / `0600`; OS keychain for keys when available; SQLCipher planned |
| Model provider | Retain prompts | Your contract with them; redaction opt-in; Strict Local avoids them |
| Search engine | Log queries + IP | Optional Tor / SOCKS5; otherwise inherent to using the web |
| Server operator (shared deploy) | Read everything on the box | Out of scope for local-first guarantees; token + TLS required in server compose |
| Supply chain | Trojaned dependency or release | Lockfiles; SBOM script; signed releases with tagged builds |

Out of scope: a compromised OS kernel or browser with full local access.

## 5. Operator surfaces

| Endpoint | Default | Gate |
|---|---|---|
| `POST /feedback` | Available (stored locally) | Auth token if configured |
| `GET /metrics` | Off until consented (`operator_metrics`); answers `403 forbidden` while off | Consent toggle + token when `profile=server` / token set |
| `GET /operator/feedback`, `/operator/traces` | Same gate as metrics | Same |
| Webhook push | Off until consented (`operator_webhooks`) | Consent toggle, then URL; optional HMAC secret |

Private threads never emit to metrics, traces, or webhooks.

## 6. Retention and deletion

- Threads: `thread_retention_days` (default 28); pinned threads are exempt.
- Traces: `trace_retention_days` (default 14).
- Settings → clear cache / wipe conversations removes local rows; wipe does not revoke a key at the provider.
- Failed or cancelled answers are not persisted.

## 7. Promises we do not make

See also `PRIVACY_DECISIONS.md` §7.

- We cannot stop upstream engines or a cloud model from seeing what you sent them.
- Redaction and tracker blocking will miss things.
- Headless Chromium can make requests the pinned fetcher would refuse — disable browser fallback on shared hosts.
- "Self-hosted by someone else" is not "private from that someone".

## 8. Keeping this document honest

Any change that adds an egress path, a new persisted field, or a new operator export must update:

1. The table in §3,
2. The diagram at the top if the shape changed,
3. The matching row in `PRIVACY_DECISIONS.md`.

CI egress test (`services/core/tests/test_egress_ci.py`) enforces §3 against the fake stack: unexpected hosts fail the build. Diagnostics → Network activity shows the live log.
