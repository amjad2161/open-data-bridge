# Meta / Facebook / Instagram setup

The bridge does not contain a Meta app, client secret or pre-authorized account.
Each operator must create or select a Meta developer app and authorize their own
Facebook Business, Page, Instagram Professional account and/or ad account.

Official starting points:

- Meta Developers: <https://developers.facebook.com/apps/>
- Business integrations: <https://www.facebook.com/settings?tab=business_tools>
- Facebook Login access tokens: <https://developers.facebook.com/docs/facebook-login/guides/access-tokens/>
- Instagram content publishing: <https://developers.facebook.com/documentation/instagram-platform/content-publishing>
- Facebook Page posts: <https://developers.facebook.com/documentation/pages-api/posts>
- Facebook video publishing: <https://developers.facebook.com/documentation/video-api/guides/publishing>

## Redirect URI

Register exactly one callback URI for the deployment being tested:

```text
https://YOUR_PUBLIC_HOST/oauth/meta/callback
```

For a local-only test, a provider may require a separately registered localhost
URI. The local bridge is not a production OAuth endpoint and must not be
exposed to the internet without the remote-bind protection described below.

## Choose scopes deliberately

Use only the scopes required by the intended workflow. Typical examples are:

- Instagram/Facebook content publishing: `instagram_basic`,
  `instagram_content_publish`, `pages_show_list`, `pages_read_engagement`,
  `pages_manage_posts`, and `pages_manage_engagement` where the workflow
  needs engagement management. Facebook Page video publishing also requires
  the permissions documented by Meta for the Video API (including
  `publish_video` where applicable).
- Paid ads and campaign management: `ads_read`, `ads_management`,
  `business_management`.

Meta may rename, restrict or require review for permissions. Confirm the exact
permission names, account types and App Review requirements in the current Meta
developer console before enabling them. The bridge does not bypass App Review,
Business Manager roles, Page roles, Instagram Professional-account
requirements, ad-account restrictions or Meta rate limits.

## Configure the bridge

The recommended local path is the interactive helper. It asks for the App
Secret with echo disabled and stores the complete Meta app configuration in
the current Windows user's DPAPI vault. The secret is not sent to ChatGPT,
written to the repository or printed to the terminal:

```powershell
python .\configure_meta.py
```

The service can also read the environment variables below. This is useful for
ephemeral CI or a separately managed secret store; do not persist the App
Secret in a `.env` file, URL, browser bookmark or chat message.

Set these variables in the process environment. Do not commit them or put the
app secret in a repository, URL, browser bookmark or chat message.

```powershell
$env:META_APP_ID = "your-app-id"
$env:META_APP_SECRET = "your-app-secret"
$env:META_API_VERSION = "vXX.X"
$env:META_REDIRECT_URI = "https://YOUR_PUBLIC_HOST/oauth/meta/callback"
$env:META_OAUTH_SCOPES = "ads_read,ads_management,business_management"
$env:META_USE_PKCE = "true"
$env:OPEN_DATA_BRIDGE_VAULT_PATH = "$env:LOCALAPPDATA\OpenDataBridge\vault.json"
python .\app.py
```

The API version is intentionally not hard-coded because Meta deprecates API
versions. Set the version currently enabled for the app in Meta's console.

When the DPAPI configuration is present, the local `/api/meta/connect-url`
endpoint and the MCP `get_meta_connect_url` tool use it automatically. The
safe `configuration` section of `get_publish_capabilities` reports only
missing field names and whether a vault configuration exists.

## Obtain the connection link

Once the variables are configured, the local API returns a short-lived,
state-bound authorization URL:

```powershell
Invoke-RestMethod http://127.0.0.1:8788/api/meta/connect-url
```

Opening `http://127.0.0.1:8788/oauth/meta/start` redirects the browser to Meta.
After authorization, Meta returns to the registered callback and the bridge
stores the token encrypted with the current Windows user's DPAPI. The bridge
never returns the token from `/api/meta/status` or an MCP result.

## Current capability boundary

The local bridge now contains a provider-specific, approval-gated Meta Graph
adapter. It supports:

- discovery of Pages and connected Instagram professional accounts through
  `/me/accounts`, with Page access tokens stored only in the encrypted vault;
- Facebook Page text/link posts through `/{PAGE_ID}/feed` and photo posts
  through `/{PAGE_ID}/photos`;
- Instagram image posts and video/Reels posts from public HTTPS media URLs
  through `/{IG_ID}/media` and `/{IG_ID}/media_publish`, including container
  status polling for video/Reels.

The adapter does not claim that a provider account is connected until OAuth and
account discovery succeed. It does not implement Facebook local-file
resumable uploads, Instagram carousels/stories, paid campaign mutation,
background scheduling, or Meta App Review. Provider limits still apply; in
particular, Meta's current Instagram documentation describes a 100 API-
published-post moving 24-hour limit and Page/role/authorization constraints.

