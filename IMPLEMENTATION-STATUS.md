# Open Data Bridge implementation status

Updated after the current verification run.

## Expansion 0.5.1 (2026-10-23)

The local bridge now includes a verified, approval-gated Meta publishing
adapter. This is not a claim of an already connected account: the runtime
continues to report blocked/unconfigured until Meta OAuth and account discovery
complete.

Implemented in code:

- `meta_publish.py` with official Graph contracts for Facebook Page text/link/
  photo posts and Instagram professional-account image/video/Reels posts from
  public HTTPS media URLs.
- Encrypted Page-token storage during `/me/accounts` discovery; no provider
  token is returned through HTTP or MCP.
- One-time `preview_publish` -> `approve_publish` -> `publish_media` flow with
  exact-plan digest, expiry, explicit phrase, token-bound approval and
  fail-closed unknown-outcome handling.
- HTTP and MCP surfaces for capabilities, account discovery, publish preview,
  approval and execution.
- `configure_meta.py` for local hidden-input Meta app configuration with the App
  Secret stored only in the Windows-user-bound DPAPI vault; the MCP capability
  response reports safe configuration diagnostics.

Verification for this expansion:

- `python -m unittest -v`: 44 tests passed.
- `python -m compileall -q .`: passed.
- Live `/health` reports `0.5.1`; live MCP `tools/list` reports 31 tools.
- Live publish smoke passed through preview, explicit approval and dry-run;
  the dry-run made no provider request and returned HTTP 200.
- Live account synchronization fails closed with
  `meta_oauth_not_connected`, as expected before external account consent.
- Synthetic Graph contract tests cover discovery, token redaction, public URL
  validation, Instagram container/publish flow, Reels status polling,
  Facebook scheduling normalization and no-network behavior when disconnected.
- No live Meta publish was attempted; no user-owned account is connected in
  the bridge vault. The capability response reports the five missing
  configuration inputs and `vault_app_configured=false`.

## Expansion 0.4 (2026-10-23)

The bridge now covers the public Windsor-style MCP surface rather than only
the initial read/query subset. The live public datasource directory was
catalogued as 367 connector IDs; those entries are explicit catalog metadata,
not fabricated adapters or connected accounts.

Implemented in code:

- `bridge_catalog.py` with the 367-source catalog plus compatibility aliases.
- Tool families for accounts, action schemas, custom fields, destinations,
  destination tasks/setup, sync status, login, subscription status and
  support-message preparation.
- Windsor-style nested filters and operators (`eq`, `neq`, `gt`, `gte`, `lt`,
  `lte`, `contains`, `ncontains`, `null`, `notnull`, `in`), date-preset aliases,
  account selection prefixes, refresh hints and local renderers.
- Explicit fail-closed responses for provider writes, custom-field persistence,
  destination scheduling, external support messages and billing.

Verification for this expansion:

- `python -m unittest -v`: 35 tests passed.
- `python -m compileall -q .`: passed.
- `git diff --check`: passed.
- Live service version after restart: `0.4.0`.

## Expansion 0.3 (2026-10-23)

The bridge was expanded from a five-tool synthetic read-only baseline to a
25-tool Windsor-style contract surface. This is an implementation expansion,
not a claim that every provider adapter is complete.

Implemented in code:

- `bridge_catalog.py` with a 19-source seed catalog, explicit implementation
  statuses, account metadata, scope requirements, options, fields and custom
  fields.
- Blended `all` connector with synthetic cross-channel rows and provenance.
- Query semantics for date presets, explicit date ranges, account selection,
  equality/membership/contains/range filters, breakdown aggregation and cursor
  pagination.
- Local JSON/CSV export and a capability/destination inventory.
- Redacted action previews for social and paid-media writes; execution remains
  fail-closed and produces no external side effect.
- Expanded MCP tool definitions and HTTP endpoints while preserving the
  original endpoints and Meta OAuth aliases.

Verification for this expansion:

- `python -m unittest -v`: 33 tests passed.
- `python -m compileall -q .`: passed.
- `git diff --check`: passed.
- Live service health: version `0.3.0`, catalog count `19`, writes disabled.
- Live MCP `tools/list`: 25 tools.
- Live blended query: grouped `all` data returned with total count and cursor.

## Current runtime state (2026-10-23)

- The local MCP service is running at `http://127.0.0.1:8788/mcp`.
- The official OpenAI `tunnel-client` Windows runtime is installed locally and
  running as a private Secure MCP Tunnel client.
- The private tunnel is connected to the ChatGPT workspace, and the custom
  `Open Data Bridge` app is installed and connected in ChatGPT.
- A live ChatGPT conversation invoked `get_connectors` through the tunnel and
  received the synthetic `demo_ads` connector. No write action was available
  or performed.
- The direct app URL is private to the connected ChatGPT workspace; it is not
  a public marketplace distribution link.
- A local marketplace entry `open-data-bridge-local` was registered with Codex,
  and `open-data-bridge@open-data-bridge-local` version `0.5.0` was installed
  and enabled in the local Codex configuration.

## Implemented and verified

| Capability | Evidence |
|---|---|
| Local-only HTTP service | `app.py`, bound to `127.0.0.1` by default |
| Health | `GET /health` and unit test |
| Connector discovery | `GET /api/connectors`, MCP `get_connectors` |
| Field discovery | `GET /api/fields`, MCP `get_fields` |
| Read query | `GET /api/data`, MCP `get_data` |
| Date filtering | Query tests |
| Fail-closed invalid fields | Query test |
| MCP JSON-RPC | `initialize`, `tools/list`, `tools/call` tests |
| Adapter contract | `connectors.py` tests |
| Retry policy primitive | 429/5xx tests |
| Windows user vault | DPAPI round-trip and corruption tests |
| OAuth state/PKCE | expiry, one-time use and URL tests |
| Meta OAuth configuration and token exchange primitive | synthetic callback, one-time state, encrypted vault storage and non-secret status tests |
| Non-loopback safety gate | startup refusal and bearer guard implemented; remote deployment not claimed |
| Private ChatGPT connection | official tunnel-client runtime, ChatGPT custom MCP app installation, live `get_connectors` call |
| Tunnel runtime | local `/healthz` and `/readyz` returned live/ready; runtime lifecycle `running`; dispatcher completed 7 requests with 0 failures |
| Expanded catalog/query contract | `bridge_catalog.py`, 19-source catalog, blended `all`, filters, breakdowns, pagination and exports |
| Expanded MCP surface | 25 tools exposed by live `tools/list` |
| Action safety contract | redacted previews and blocked execution test; no write side effect |
| Meta publish contract | 44-test synthetic Graph adapter coverage; live provider connection not present |

## Current 0.5.1 contract evidence

| Capability | Evidence |
|---|---|
| Windsor datasource inventory | `WINDSOR_CONNECTOR_IDS`: 367 IDs from the public directory |
| Expanded MCP surface | `tool_definitions()` exposes 31 local tools including guarded Meta publishing |
| Nested filter semantics | `test_nested_filters_and_windsor_aliases` |
| Fail-closed write boundary | destination tasks, custom fields, contact and `execute_action` return blocked/no-side-effect results |
| Private app metadata | private description updated to the guarded publishing surface; local 0.5.1 source is running |
| Remote ChatGPT app schema | fresh chat exposed 31 tools and successfully called read-only `get_publish_capabilities`; older open chats may retain 5 tools |
| Local Codex plugin | last independently verified installation was 0.5.0; the loopback MCP endpoint now serves 0.5.1 |
| Public source repository | `https://github.com/amjad2161/open-data-bridge`; the current 0.5.1 source update still requires publication verification |

## Deliberately not implemented yet

- Provider-specific OAuth policies and adapters beyond the Meta Facebook-Login path.
- Real provider client secrets in source control or plaintext configuration.
- Live Meta account discovery and publish acceptance against a user-owned target.
- Destination writers.
- Background scheduler.
- Refresh-token rotation and provider token refresh.
- Generic write actions and paid campaign mutation.
- Automatic account connection.
- Live Meta OAuth/account discovery and real provider publish acceptance.
- Facebook local-file resumable upload, Instagram local resumable upload,
  carousels and stories.
- Live adapters for the 367 catalog-only sources; catalog presence is not an
  account connection or provider implementation.
- Production-grade destination writers and durable sync scheduling.
- Public multi-tenant OAuth 2.1 identity and per-tenant isolation.

## Compatibility boundary

The local MCP contract implements a local read/query surface plus an explicit,
approval-gated Meta publishing subset. It is not claimed to be Windsor.ai
compatible at the wire or semantic level, and it does not use Windsor private
endpoints or code.

## Acceptance gates for the next phase

1. Run `python .\configure_meta.py` locally after obtaining the App Secret in
   Meta's own console. It must never enter source control, chat, logs or MCP
   responses.
2. Complete OAuth with the exact publishing scopes, run `sync_meta_accounts`,
   and verify the returned Page/Instagram capability records without exposing
   tokens.
3. Perform a live read-only Graph verification against the user-owned account.
4. For the first real post, use an explicitly approved test caption/media and
   target; verify the provider result before any further publishing.
5. Add resumable local-file upload, carousels/stories, and durable scheduling
   only as separate verified phases.
6. Reopen or refresh any older ChatGPT conversation that still holds a frozen
   five-tool snapshot; a fresh-chat 31-tool verification already passed.
7. Deploy behind HTTPS and per-user authentication before enabling any shared
   or public ChatGPT connection.

