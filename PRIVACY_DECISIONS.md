# GleanWise: Privacy and Architecture Decision Record

One place for every privacy-related decision and the architecture that follows from it.

Related: [`PRIVACY.md`](PRIVACY.md) (threat model and data flows), [`ARCHITECTURE.md`](ARCHITECTURE.md), [`UX_UI.md`](UX_UI.md).

## 1. Context and goal

Competing open-source tools stop at "self-hosted". Our angle is **verifiable privacy**: the user controls every place data can leave the machine and can check it. We do not claim that nothing ever leaves (see §7).

Status legend used below:

| Status | Meaning |
|---|---|
| **Shipped** | In the current codebase and installer |
| **Planned** | Decided; not built yet |
| **Deferred** | Decided in principle; waiting on a spike or a later release |

## 2. Decisions

| # | Decision | Status |
|---|---|---|
| D1 | Position on verifiable privacy, not privacy theatre | Shipped (position + no telemetry) |
| D2 | Baseline localhost hardening, not optional | Shipped |
| D3 | Single local egress gateway for all outbound traffic | Shipped |
| D4 | Network activity page, CI egress test, public threat model | Shipped |
| D5 | Strict Local mode | Shipped |
| D6 | Private threads | Shipped |
| D7 | Encrypted storage; keys in the OS keychain with automatic unlock | Partial (keychain + file perms Shipped; SQLCipher Deferred) |
| D8 | Optional Tor / SOCKS5 routing; Tor is an optional download | Shipped (SOCKS5 via gateway; Tor not bundled) |
| D9 | Local PII redaction before cloud model calls | Shipped |
| D10 | Tracker and ad blocking in the Playwright fetcher | Shipped (suffix blocklist + ephemeral context; not full EasyList) |
| D11 | Per-answer data-flow indicator | Shipped |
| D12 | Operator endpoints gated; consent when enabling export surfaces | Shipped |
| D13 | Signed releases, pinned dependencies, SBOM | Partial (pins + SBOM script Shipped; signing with tagged release) |

### D1. Verifiable privacy

Every outbound request is user-initiated. No accounts, no product telemetry, no phoning home. The app will show what left the machine (D4), and CI will fail if anything unexpected does (D4).

**Shipped today:** no telemetry client; LiteLLM / search / fetch only run when the user asks a question or tests a connection; secrets are never returned by the settings API.

### D2. Baseline localhost hardening

The out-of-box app runs as a background service on localhost, so a malicious website could try to reach it (DNS rebinding, cross-site requests) and read history or spend API keys.

- Bind to `127.0.0.1` only by default.
- Host allowlist (defeats DNS rebinding) and Origin check on mutating requests (defeats CSRF).
- Optional per-install bearer token (`GLEANWISE_API_TOKEN`); required when binding off loopback or when `profile=server`.
- Same rules on the OpenAI-compatible and MCP surfaces.
- Strict CSP, `frame-ancestors 'none'`, nosniff for the served UI.
- SSRF pinning on page fetch (resolved address must stay public unless the operator explicitly allows private for labs).

**Shipped.** A future installer pass will generate a random token at first install and store it for the local UI (today the token is opt-in on the local profile).

### D3. Egress gateway

All outbound traffic from core, SearXNG and Playwright passes through one local forward proxy we own.

- Logs host, port and bytes. It does not decrypt TLS, so it cannot see paths or content.
- Enforces egress rules, including Strict Local (D5).
- Applies Tor / SOCKS5 routing (D8).
- Direct outbound sockets from any component are blocked (env + process policy).

**Wiring (closed):** HTTP CONNECT proxy on loopback, on a stable port persisted in the data directory. Each component identifies its purpose through the proxy credentials (`purpose-search`, `purpose-fetch`, …) or a `Proxy-Purpose` header. A **managed** SearXNG gets a generated settings file with `outgoing.proxies` pointing at the gateway; an **external** SearXNG cannot be configured by us and is outside the gateway (documented in `PRIVACY.md`, and the core → SearXNG hop is still logged). Playwright uses `proxy.server`; Playwright uses `proxy.server`; the core HTTP client uses the same URL via env (`HTTPS_PROXY` / explicit client config). Non-HTTP protocols are not used by GleanWise; if a dependency opens one, the CI egress test (D4) fails the build.

### D4. Network activity page, CI egress test, threat model

- Diagnostics → **Network activity**: every outbound request (host, purpose, bytes, time), fed by the gateway log.
- CI job: run the app against the fake search / page / LLM stack; fail on any connection outside the expected set.
- [`PRIVACY.md`](PRIVACY.md) holds the public threat model and data-flow diagram; update it with every feature that adds an egress path.

### D5. Strict Local mode

Hard-blocks any model or embedding call to a non-local endpoint, enforced in `llm/` and `embed/` **and** at the gateway — not only in the UI.

- "Local" means loopback or an explicitly allowlisted LAN address (for example an Ollama host).
- Embedder and reranker must be local too (`embedder=local` / `hash`, local cross-encoder).
- Search and page fetching still leave the machine unless Tor / SOCKS5 is on (D8); the UI must say so.

### D6. Private threads

Nothing is persisted for that thread: no thread or message rows, no cached documents or chunks, no vectors, no feedback or trace events, and nothing sent to operator endpoints or webhooks. State lives in memory and is discarded when the thread closes (or the process exits). Deep mode works in memory. Private threads do not appear in the sidebar history.

**UI (closed):** entry point is a lock affordance next to "New search". While active: lock badge in the composer, no rename/pin, closing the tab or choosing "Forget" wipes memory. Switching away without forgetting prompts once.

### D7. Encrypted storage and keychain

- **Target:** local SQLite encrypted with SQLCipher; DB key and BYOK API keys in the OS keychain (Keychain / Credential Locker / Secret Service), never in plaintext config; unlock automatic on login.
- **Windows:** the core runs in WSL and cannot reach the Windows credential store directly, so a small Windows-side bridge stores and releases the key when the signed installer ships.
- **Server profile:** Postgres encryption at rest is the operator's responsibility.

**Interim (Shipped):** data directory `0700`, settings / secret files `0600`, API never returns raw keys (only `*_set` booleans). SQLCipher lands after the compatibility spike (§6).

### D8. Tor / SOCKS5 routing

Optional, independently for SearXNG upstream queries (managed SearXNG only, because it depends on D3 routing) and for page fetching. Tor is **not** bundled: the first-run / settings flow offers an optional Tor download (or points at a system `tor`) when the user enables it. A user-supplied SOCKS5 URL is also accepted. Routing always goes through the egress gateway (D3).

### D9. PII redaction — scope closed

- **Default: off.** Opt-in toggle: "Redact personal details before cloud models".
- Applies only when the configured LLM endpoint is **not** local (same definition as D5). Local models skip redaction.
- Entity types in v1: email addresses, phone numbers, common government ID patterns (US SSN-shaped, credit-card-shaped). Proper names are **out of scope** for v1 (too many false positives).
- Placeholders are restored in the streamed answer only; they are never written to traces, feedback, or webhooks.
- Best-effort; the UI labels it as such (see §7).

### D10. Tracker and ad blocking

Applied inside the Playwright fetcher so fetched pages cannot load third-party trackers. Ephemeral browser context per fetch, no cookies or storage, stripped `Referer`, stable product user agent.

This lives in the browser, not the gateway, because the gateway does not decrypt TLS.

**Shipped today:** markdown images are proxied through the core (closes tracking / exfiltration via `<img>`), fetch respects robots, response size caps. Full EasyList-style blocking in Playwright is Planned.

### D11. Per-answer data-flow indicator

A small control on each answer opens a popover: engines queried, pages fetched, local or cloud model, proxy / Tor on or off, redaction applied or not. Built only from events already on the wire (no extra egress).

### D12. Operator endpoints

`/metrics`, `/operator/*`, JSONL trace export and webhook push expose usage data.

- **Shipped:** on `profile=server`, these refuse to run without `GLEANWISE_API_TOKEN`. Settings never echo secrets. Webhook payloads are HMAC-signed when a secret is set. Off-by-default toggles in Settings → Privacy with an explicit consent dialog the first time each surface is enabled; Private threads (D6) never emit to them.
- **Deferred:** optional redaction of query text in exported traces.

Thumbs feedback stays local to the instance (it is how the reference UI learns what to improve) and is covered by wipe / retention; it is not sent to us.

### D13. Supply chain

Signed releases and installers, pinned lockfiles (`uv.lock`, `pnpm-lock.yaml`), an SBOM published with each release, and a third-party review once the privacy suite in §4 lands.

**Shipped:** lockfiles and reproducible `uv` / `pnpm` installs. Signing and SBOM ride with the first tagged release.

## 3. Architecture changes

| Component | Change |
|---|---|
| **Egress gateway** (new) | Local forward proxy. Core, SearXNG and Playwright use it. Rules and logs feed Network activity. |
| **`llm/` / `embed/`** | Enforce Strict Local; run D9 redaction before cloud calls. |
| **`index/` (SQLite)** | SQLCipher-backed once the spike passes; key from keychain at startup. |
| **Keychain bridge** (new, Windows) | Windows-side helper for the WSL-hosted core. |
| **`pipeline/`** | Private-thread path: skip persistence, cache writes, feedback, traces, webhooks. |
| **`fetch/`** | Ephemeral Playwright contexts, tracker blocklist, stripped headers, gateway routing. |
| **`api/`** | Localhost hardening on every surface, including OpenAI-compatible and MCP. |
| **UI** | Strict Local toggle + badge, private-search entry, Network activity, data-flow indicator, privacy step in setup, consent for operator exports. |

Deployment

- Out-of-box: bind loopback; installer will own the gateway and (on Windows) the keychain bridge.
- Server profile: operators own storage encryption and auth. Operator export surfaces stay gated as in D12.

## 4. Milestone impact

| When | What |
|---|---|
| **Now (baseline)** | D1 position, D2 hardening, interim D7 file permissions, image-proxy part of D10, operator token gate (D12), pinned deps (D13), this ADR + `PRIVACY.md` |
| **With fetch hardening** | D3 egress gateway lands with Playwright blocklist completion (D10) — fetch already depends on a single egress story |
| **Privacy suite** | **Shipped** except SQLCipher + Windows keychain bridge (Deferred) and release signing (with first tag). D4–D6, D8–D12, keychain helper, SBOM script, tracker blocklist. |

## 5. Risks

- **Scope.** Gateway + hardening are foundational and cheap early; the rest of the suite can slip without breaking search-and-answer.
- **SQLCipher.** Must coexist with FTS5 and sqlite-vec — unverified; blocked on the spike in §6.
- **Windows bridge.** Extra binary to build and update with the signed installer.
- **Gateway without TLS decryption.** Host-level visibility only; path rules and tracker blocking stay in the browser.
- **Redaction quality.** Best-effort; expect misses and some answer degradation when enabled.

## 6. Closed and remaining open items

Closed in this revision

- PII redaction scope (D9): opt-in; cloud-only; email / phone / ID-shaped / card-shaped; no proper names in v1.
- Gateway wiring (D3): loopback HTTP CONNECT; SearXNG `outgoing.proxies` + Playwright `proxy.server` + core proxy env.
- Private-thread UI (D6): lock entry point, in-memory only, forget on close.
- Interim storage posture (D7): `0700` / `0600` until SQLCipher ships.

Still open (need spikes, not product debate)

1. **SQLCipher × FTS5 × sqlite-vec** compatibility and migration from plaintext DB.
2. **Windows keychain bridge** IPC shape (named pipe vs local socket) for the signed installer.

Closed with the privacy suite: CI egress allowlist against the fake stack (`tests/test_egress_ci.py`); Network activity UI; Strict Local; private threads; SOCKS5; PII redaction; tracker blocklist; data-flow indicator; operator consent toggles; keychain helper; `scripts/sbom.sh`.

## 7. Limits we state openly

- Upstream search engines still see queries from your IP unless you route through Tor or a SOCKS5 proxy.
- A cloud model still sees the query and retrieved text (minus whatever redaction caught). Only Strict Local keeps model calls on the device.
- Redaction and tracker blocking are best-effort.
- On a server someone else runs, that operator controls the machine.
- A compromised operating system is out of scope.
- Browser SSRF protections for the optional headless Chromium are best-effort: the plain fetcher pins resolved addresses; pages rendered in Chromium can issue their own requests. Leave browser fallback off on shared servers.
