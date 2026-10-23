# Code review and release gate

Review mode: defect-first inspection of the complete current working tree,
including the original local MCP implementation, Meta OAuth additions, vault
persistence changes, tests and setup documentation.

## Expansion review — 0.5.1

- `meta_publish.py` is limited to Graph API paths verified against Meta's
  current documentation: Facebook Page text/link/photo posts and Instagram
  professional-account image/video/Reels posts from public HTTPS URLs.
- Provider credentials cross the boundary only from the DPAPI-backed vault;
  they are sent in an Authorization header and are not returned, logged or
  placed in query parameters.
- Account discovery stores Page access tokens under vault keys and returns only
  IDs, names, tasks and readiness booleans.
- Publishing requires an exact preview digest, explicit approval phrase and a
  one-time short-lived grant. An error after a provider request starts is
  reported as `unknown` and cannot be retried automatically, preventing a
  duplicate-post retry.
- Synthetic Graph tests pass; no live Meta request or social post was made.
- The adapter deliberately does not claim local-file Facebook video upload,
  Instagram carousel/story support, paid-ad mutation, or background scheduling.

## Expansion review (2026-10-23)

### Expansion 0.4 review

- The public Windsor datasource directory was represented as 367 explicit
  catalog IDs; unavailable entries remain catalog-only and cannot be queried.
- The MCP contract now includes account discovery, action schemas, destination
  setup/task contracts, custom-field validation, sync/login/subscription status
  and support-message preparation.
- Nested filters, operator aliases, account prefixes and date-preset aliases
  are covered by tests.
- Provider writes, destination scheduling, provider custom-field persistence,
  billing and outbound support messages remain fail-closed.
- The local service has 44 passing tests. A fresh ChatGPT conversation was also
  verified against the updated app and exposed 31 tools; an already-open chat
  may retain the old five-tool snapshot until it is refreshed or reopened.

- The previous five-tool surface was expanded to 25 tools and covered by new
  tests rather than represented as documentation only.
- Catalog-only providers are marked unavailable and fail closed if queried.
- Blended data is explicitly synthetic and carries connector provenance.
- Filters, grouping and pagination validate connector fields and operators.
- Action previews redact token-like payload keys. `execute_action` is blocked,
  requires a preview, and records no external side effect.
- The service remains local single-user infrastructure. No public multi-tenant
  authentication or production write path was introduced by this expansion.

## Expansion findings and limits

1. The catalog contains 367 canonical entries plus compatibility aliases, but
   only two synthetic data sources are executable. This is intentional and
   visible in every connector descriptor.
2. Meta OAuth and the provider adapter are implemented, but no live Meta
   account was connected or used by the custom bridge.
3. Destination names are capability inventory only. No warehouse/BI writer or
   scheduler is claimed.
4. External provider quotas and rate limits remain in force; the bridge cannot
   truthfully promise unlimited operation.

## Current operational review

- Local implementation: 44 automated tests pass; compilation and whitespace
  checks pass; no credential literal was found in the source tree.
- Private ChatGPT integration: verified through the official tunnel-client
  runtime and a real `get_connectors` call from ChatGPT; 7 dispatcher requests
  completed with 0 failures.
- Local Codex integration: the 0.5.0 package installation was previously
  verified; the running loopback MCP endpoint now serves the 0.5.1 source.
- Meta setup: an existing development app is available and its required test
  permissions are ready, but read-only URI validation showed that the loopback
  callback is not registered. Meta also requires password re-authentication
  before exposing the App Secret. No password was collected and no bypass was
  attempted.

## Findings fixed

1. MCP `get_data` ignored date filters. The MCP path now applies the same date
   semantics as the HTTP path and rejects inverted ranges.
2. Invalid JSON-RPC `params`, non-string fields and non-string dates could raise
   uncaught exceptions. These inputs now return structured `-32602` errors.
3. A non-loopback bind could have exposed the local service without an explicit
   secret. Startup now refuses that configuration, and the handler requires a
   Bearer secret for remote requests.
4. Vault writes used a shared temporary filename without serialization or an
   `fsync`. Writes now use a process lock, flush and `fsync` before atomic
   replacement, and read/decryption failures remain fail-closed.
5. Meta OAuth configuration could silently build an unsafe redirect or malformed
   API-version URL. Configuration now requires an explicit version, HTTPS for
   public redirects, and a one-time state.

## No unresolved local correctness findings

The current local test suite covers the fixed paths, synthetic Meta token
exchange, token non-disclosure, state replay, malformed input, date filtering,
loopback/remote authorization behavior and vault corruption. `git diff --check`
also passes.

## Release blockers outside the local code

These are not claims of completion and require external state or provider
authorization:

- The existing development app and required test permissions are present, but
  the loopback redirect is not registered and the App Secret has not been
  supplied to the local process because Meta requires a password
  re-authentication step. No live
  Meta OAuth or real-account connection is therefore claimed.
- No live Meta OAuth, account discovery, Graph API, Marketing API or ad-account
  read test has run.
- The Meta adapter has no live publish acceptance; generic ad/destination writes
  remain disabled.
- The current server is single-user bootstrap infrastructure. It is not a
  multi-tenant identity/session system and must not be exposed as one.
- It does not yet implement the complete OAuth 2.1 MCP authorization contract
  required for a public authenticated ChatGPT plugin: protected-resource
  metadata, authorization-server discovery, token issuance and token
  verification/scope enforcement on every request are still missing.
- ChatGPT requires a remote HTTPS MCP endpoint or supported tunnel; the local
  `127.0.0.1` endpoint is not a direct ChatGPT connection target.
- Public source repository: `https://github.com/amjad2161/open-data-bridge`.
  The 0.5.1 source update must be published and independently checked after
  the local commit.

