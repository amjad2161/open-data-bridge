# Open Data Bridge

Local-first, open-source data bridge for connecting user-owned business accounts to reports, exports and MCP-compatible assistants.

This is an independent implementation. It does not copy Windsor.ai code, branding, private endpoints or credentials.

## Current status

- Runnable Python standard-library HTTP service.
- Local health endpoint.
- Connector registry with synthetic demo data.
- Read-only query endpoint with field validation and date filtering.
- MCP JSON-RPC endpoint at `/mcp` with `initialize`, `tools/list` and read-only `tools/call`.
- Provider adapter contracts, registry and retry-policy primitives in `connectors.py`.
- An example connector configuration with disabled real connectors and explicit scopes.
- Windows-user-bound DPAPI vault primitives in `vault.py`; no credentials are created or connected automatically.
- Provider-neutral OAuth state/PKCE primitives in `oauth.py`; no client IDs, secrets or token exchange are included.
- Meta OAuth start/callback/status flow in `meta_oauth.py`; it is fail-closed until the operator supplies an app and explicit scopes.
- Approval-gated Meta publishing adapter in `meta_publish.py`: Facebook Page text/link/photo posts and Instagram professional-account image/video/Reels posts from public HTTPS media URLs. Page/Instagram account discovery stores provider tokens only in the encrypted local vault.
- OpenAI/ChatGPT deployment and MCP setup guidance in `OPENAI-SETUP.md`.
- Facebook/Instagram/Meta setup and authorization boundaries in `META-SETUP.md`.
- A durable verification record is maintained in `VERIFICATION.md`.
- Review findings and release gates are recorded in `CODE-REVIEW.md`.
- Claude Code and Cursor configuration templates targeting the local server.
- No real-account connection has been attempted.

## Expanded Windsor-style contract (version 0.5.0)

The bridge now exposes a broader, explicit contract rather than only the
original five read-only tools:

| Surface | Endpoint/tool | Status |
|---|---|---|
| Identity | `/api/profile`, `get_current_user` | Local single-user status |
| Capability inventory | `/api/capabilities`, `get_capabilities` | Implemented with evidence/status labels |
| Source inventory | `/api/connectors`, `get_connectors` | 2 active synthetic sources; 367 canonical catalog sources plus compatibility aliases |
| Connection requirements | `/api/connect-info`, `get_connector_connect_info` | Implemented; live OAuth depends on provider setup |
| Schema/options | `/api/fields`, `/api/options`, `/api/custom-fields` | Implemented |
| Unified data | `/api/data`, `get_data` | Implemented for synthetic sources |
| Blended data | connector `all` | Synthetic cross-channel data with provenance |
| Export | `/api/export`, `export_data` | Local JSON/CSV |
| Publishing/ad actions | `/api/actions/*`, `preview_action`, `execute_action` | Generic action contract; paid/ad writes remain blocked |
| Meta publishing | `/api/publish/*`, `preview_publish`, `approve_publish`, `publish_media` | Verified public-URL Facebook/Instagram adapter; OAuth/account/approval required |
| Meta accounts | `/api/meta/accounts`, `sync_meta_accounts` | Provider discovery plus encrypted Page-token storage; no secrets returned |
| Warehouses/BI | `/api/destinations`, `get_destinations` | Catalog/status only |
| Accounts and action schemas | `/api/accounts`, `/api/actions`, `get_accounts`, `list_actions` | Synthetic account inventory and explicit JSON schemas |
| Destination operations | `/api/destinations/tasks`, `/api/destinations/setup-info` | Contract/status only; scheduling and writers blocked |
| Operational surface | `get_sync_status`, `get_subscription_url`, `get_windsor_login_url`, `contact_windsor` | Local status; no billing, login or outbound messaging |
| Custom fields | `get_custom_fields`, `create_custom_field` | Discovery/validation; provider persistence blocked |

The full catalog intentionally marks unavailable providers as `catalog_only`;
catalog presence is not a live account connection. This is a
compatibility-oriented contract, not a claim of Windsor.ai data parity.

The local tool surface is broader than an already-open private ChatGPT
conversation can retain. A fresh ChatGPT conversation was verified against the
updated app and exposed all 31 tools; an older conversation may continue to
show its original five-tool snapshot until it is refreshed or reopened.

The same 0.5.0 package is also installed and enabled in the local Codex plugin
marketplace as `open-data-bridge@open-data-bridge-local`; it points directly at
the running loopback MCP server and therefore uses the full local tool surface.

## Hard limits

“Unlimited” cannot be guaranteed: external providers impose quotas, rate limits, scopes and terms. The bridge itself has no subscription, per-query credit system or vendor billing. Real accounts require the user to create and authorize provider applications or OAuth connections.

## Run

```powershell
python .\app.py
```

The service binds to `127.0.0.1:8788` by default.

```powershell
Invoke-RestMethod http://127.0.0.1:8788/health
Invoke-RestMethod http://127.0.0.1:8788/api/connectors
Invoke-RestMethod 'http://127.0.0.1:8788/api/data?connector=demo_ads&fields=date,campaign,spend,conversions&date_from=2026-01-01'
```

MCP clients should use the local endpoint configured in `mcp.json`:

```text
http://127.0.0.1:8788/mcp
```

## Security posture

- Localhost-only by default.
- No secrets in the repository.
- Demo data is synthetic.
- Real provider adapters must use official APIs and user-owned credentials.
- A non-loopback bind is refused unless `OPEN_DATA_BRIDGE_SHARED_SECRET` is configured.
- Vault corruption or decryption failure is fail-closed; the code does not auto-repair or replace uncertain vault data.
- Generic write actions and ad mutations remain disabled.
- Meta publishing is an explicit exception with a separate preview/approval/one-time-grant gate; it remains blocked until provider OAuth, Page/Instagram discovery and required permissions are present.
- Local files are not silently uploaded. Instagram media must be publicly reachable over HTTPS; Facebook video and local resumable upload are not part of this verified adapter yet.

## OpenAI and Meta boundary

The local MCP endpoint is not directly reachable by ChatGPT. Use a public HTTPS
MCP deployment or a supported Secure MCP Tunnel, then follow `OPENAI-SETUP.md`.
The Meta OAuth flow can produce a user-specific authorization URL only after a
Meta app, redirect URI, API version and scopes are configured. The verified
publisher uses official Graph endpoints, but it does not bypass Meta review,
roles, Page Publishing Authorization, account type requirements or provider
rate limits. Paid campaigns, local-file video upload, carousels, stories and
background scheduling remain separate work.

