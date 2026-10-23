# Verification record

Verification run: current workspace state.

## Expansion verification (2026-10-23) — 0.5.1

| Check | Result |
|---|---|
| Unit/integration suite | 44 tests passed |
| Python compilation | passed |
| Meta adapter contract | discovery, vault redaction, URL validation, Facebook Page text scheduling, Instagram image/Reels flow and disconnected no-network path passed |
| Approval gate | exact-plan digest, explicit phrase, one-time approval grant and unknown-outcome fail-closed path covered |
| Live local publish surface | `/health` = `0.5.1`; capabilities report Meta disconnected, approval required, no vendor credits, no secrets in responses and safe missing-configuration diagnostics |
| Live local publish smoke | preview → explicit approval → dry-run returned HTTP 200, `dry_run`, and `provider_request_made=false` |
| Live local MCP inventory | `tools/list` returned 31 tools, including `get_publish_capabilities`, `sync_meta_accounts`, `preview_publish`, `approve_publish` and `publish_media` |
| Live account sync guard | `/api/meta/accounts/sync` returned `blocked / meta_oauth_not_connected`; no provider request was made |
| Live Meta provider | not attempted; no Meta OAuth/account is connected in the custom bridge |
| Local file upload | not claimed; public HTTPS media URL required for the implemented media path |

## Expansion verification (2026-10-23)

### Expansion 0.4

| Check | Result |
|---|---|
| Unit/integration suite | 35 tests passed |
| Python compilation | passed |
| Whitespace validation | `git diff --check` passed |
| Live server version | `0.4.0` after restart |
| Local catalog | 367 canonical public datasource IDs plus compatibility aliases; active synthetic `demo_ads` and `all` |
| Local MCP tool inventory | Expanded contract includes query, accounts, actions, destinations and operational tools |
| Live blended query | grouped source query returned rows, total count and cursor |
| Action safety | preview redacted token-like keys; execution blocked with zero side effects |

The 367-entry catalog is catalog metadata. It does not prove that any of
those provider adapters or user accounts are connected.

This proves the expanded local contract is internally coherent. It does not
prove any live provider API, account permission, publishing action, quota
behavior or Windsor.ai parity.

## Live integration evidence (2026-10-23)

| Check | Result |
|---|---|
| Official OpenAI tunnel-client install | Windows amd64 release `v0.0.17`; SHA-256 verified against the release checksum manifest |
| Tunnel runtime health | `/healthz` = `live`; `/readyz` = `ready`; lifecycle = `running` |
| Tunnel dispatcher | 7 completed requests; 0 failures |
| ChatGPT custom app | `Open Data Bridge` installed and connected in the private workspace |
| ChatGPT MCP call | `get_connectors` executed through the private tunnel and returned `demo_ads`; 0 write actions |
| Remote ChatGPT fresh-chat verification | read-only `get_publish_capabilities` succeeded; the new chat exposed 31 tools, reported Meta disconnected, no vendor credits and approval-gated writes |
| Local Codex plugin installation | the 0.5.0 installation was previously verified and its MCP config targets `127.0.0.1:8788/mcp`; the running source is now 0.5.1 |
| Local 0.5.0 plugin artifact | `.artifacts/open-data-bridge-0.5.0.zip`; SHA-256 `62CBA2E9D18A65A960B38E5F3544051D9D0369D264CF9550166A8398274D39CE` |
| Local 0.5.1 plugin artifact | `.artifacts/open-data-bridge-0.5.1.zip`; SHA-256 `7982E45753AD59EEC07A8C542AEF1084BD5D976F1AF5629D016440FD0DA16739`; archive contains only `.codex-plugin/plugin.json` and `.app.json` |
| Public GitHub source | `https://github.com/amjad2161/open-data-bridge`; main verified at commit `a146fdf4948110b6056c8d6c72d6742193eb278a`, including `configure_meta.py` and the 0.5.1 server |
| Meta redirect configuration | read-only Meta validation returned `invalid redirect URI` for `http://127.0.0.1:8788/oauth/meta/callback`; it has not been saved |

## Commands and results

| Command | Result |
|---|---|
| `python -m unittest -v` | 44 tests passed |
| `python -m compileall -q .` | passed |
| `python -c "import app, connectors, meta_oauth, oauth, vault; print('imports: ok')"` | passed |
| live `GET /health` on `127.0.0.1:8788` | verified after the 0.5.1 restart; local writes remain false |
| live connector discovery | synthetic `demo_ads` returned |
| live field discovery | `date`, `campaign`, `spend`, `conversions` returned |
| live date-filtered query | one matching synthetic row returned |
| live MCP initialize/tools/list/tools/call | passed in unit and smoke coverage |
| live publish capabilities/accounts/preview/approve/dry-run | passed; account sync remained blocked because Meta OAuth is not connected |

## What this proves

- The local service can start and answer its implemented endpoints.
- The implemented local read/query surface and approval-gated Meta contract are internally coherent.
- Invalid fields fail closed.
- Adapter, OAuth-state and vault primitives load and pass their tests.
- No provider account or external credential is required for the demo path.
- Meta OAuth tests use a synthetic token endpoint and never contact Meta.
- A non-loopback server cannot start without `OPEN_DATA_BRIDGE_SHARED_SECRET`.
- The private ChatGPT tunnel forwards real MCP requests to the local service.
- The local Codex plugin package is installed and enabled, with its MCP endpoint
  pointing at the live local service.
- The live local publisher exposes 31 MCP tools and its dry-run path was
  verified without a provider request or vendor-credit dependency.
- The ChatGPT app is connected, but the live result is still the synthetic
  connector because no real provider account is configured in the bridge.
- The private plugin metadata page previously reported version `0.4.0`; the
  local source and running service are now `0.5.1`. An already-open ChatGPT
  conversation can retain an older five-tool snapshot, while a fresh ChatGPT
  conversation was verified against the updated app and exposed 31 tools. This
  is expected per-app-session snapshot behavior.

## What this does not prove

- Provider API correctness.
- OAuth token exchange or refresh behavior.
- Live Meta OAuth, Meta App Review, account discovery or Graph/Marketing API behavior.
- A real publish to Facebook or Instagram; no content was sent.
- Real account permissions.
- Data parity with Windsor.ai or any source platform.
- Destination delivery, scheduling, retry persistence or schema evolution.
- Security of a production deployment beyond the stated local-only boundary.
- Unlimited use; provider quotas and rate limits remain external constraints.

See `CODE-REVIEW.md` for the defect-first review and release blockers.

