# OpenAI / ChatGPT MCP setup

Open Data Bridge exposes a standard MCP endpoint. OpenAI/ChatGPT can be the
primary host, while Claude, Cursor and other MCP clients may use the same
contract when they support the configured transport and authentication.

## Important deployment boundary

The default endpoint is:

```text
http://127.0.0.1:8788/mcp
```

That is suitable for local MCP clients only. ChatGPT does not connect directly
to a developer-machine localhost MCP server. Use a public HTTPS deployment or
an OpenAI-supported Secure MCP Tunnel. Never publish an unauthenticated
localhost service by binding it to `0.0.0.0`.

## ChatGPT connection

In ChatGPT web, open Plugins, select `+`, choose **Add custom MCP server**, enter
the public HTTPS `/mcp` URL, configure authentication, review the risk warning,
and create the plugin. Workspace administrators may need to permit and publish
the app. After tool changes, the workspace may need to refresh the frozen tool
snapshot.

Current official OpenAI guidance:

- <https://help.openai.com/en/articles/12584461-connecting-custom-mcp-servers-in-chatgpt>
- <https://help.openai.com/en/articles/12584461-developer-mode-and-full-mcp-connectors-in-chatgpt>

Full write/modify MCP support is plan- and workspace-dependent. The bridge's
generic ad/destination write tools remain blocked. Meta publishing is exposed
as a separate approval-gated surface (`preview_publish` → `approve_publish` →
`publish_media`) and only works after the local OAuth/account prerequisites
are genuinely present. The private ChatGPT app snapshot must be rescanned by
the host before newly added tools become visible remotely.

## Remote-bind protection

When the service is bound to a non-loopback host, startup refuses to continue
unless `OPEN_DATA_BRIDGE_SHARED_SECRET` is set. Every request except health and
the state-protected OAuth callback must carry:

```text
Authorization: Bearer YOUR_SHARED_SECRET
```

This is a single-user bootstrap guard, not a multi-tenant identity system and
not the OAuth 2.1 authorization contract expected by an authenticated public
ChatGPT plugin. A real public deployment must add protected-resource metadata,
an authorization server, token issuance, token signature/issuer/audience/
expiry/scope validation on every MCP request, tenant isolation, CSRF/session
controls, encrypted server-side token storage and audit logging before it is
offered to multiple users.

## Other clients

Use the client-specific MCP configuration with the remote `/mcp` endpoint. The
local templates are `mcp.json` and `claude-plugin.json`; replace the endpoint
with the deployed HTTPS URL and configure the same authentication policy in
the client. Client-specific installation is intentionally not performed by
this repository because it depends on the user's host and account policy.

