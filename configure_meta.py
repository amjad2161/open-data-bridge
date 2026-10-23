"""Configure Meta OAuth locally without placing an app secret in chat or source.

Run this script in the same Windows user context as the bridge.  The app
secret is read with echo disabled and written only to the DPAPI-protected local
vault.  The script prints configuration status, never the secret.
"""

from __future__ import annotations

import json
import os
import re
from getpass import getpass
from urllib.parse import urlparse

from meta_oauth import MetaOAuthConfig, default_vault_path
from vault import UserVault, VaultError


DEFAULT_SCOPES = (
    "instagram_basic,instagram_content_publish,pages_show_list,"
    "pages_read_engagement,pages_manage_posts"
)


def _prompt(label: str, default: str = "") -> str:
    suffix = f" [{default}]" if default else ""
    value = input(f"{label}{suffix}: ").strip()
    return value or default


def _validate(config: MetaOAuthConfig) -> None:
    if config.missing:
        raise ValueError("missing: " + ", ".join(config.missing))
    if not re.fullmatch(r"v\d+\.\d+", config.api_version):
        raise ValueError("API version must look like vXX.X")
    parsed = urlparse(config.redirect_uri)
    if parsed.fragment or not parsed.netloc:
        raise ValueError("redirect URI must include a host and no fragment")
    if parsed.scheme == "https":
        return
    if parsed.scheme == "http" and parsed.hostname in {"127.0.0.1", "localhost", "::1"}:
        return
    raise ValueError("redirect URI must use HTTPS, except for loopback local testing")


def main() -> None:
    print("Open Data Bridge - local Meta OAuth configuration")
    print("The App Secret is not echoed and is stored only in the Windows DPAPI vault.")
    app_id = _prompt("Meta App ID", os.environ.get("META_APP_ID", ""))
    app_secret = getpass("Meta App Secret (hidden): ").strip()
    api_version = _prompt("Meta Graph API version", os.environ.get("META_API_VERSION", ""))
    redirect_uri = _prompt(
        "OAuth callback URI",
        os.environ.get("META_REDIRECT_URI", "http://127.0.0.1:8788/oauth/meta/callback"),
    )
    scopes = _prompt("OAuth scopes (comma-separated)", os.environ.get("META_OAUTH_SCOPES", DEFAULT_SCOPES))
    use_pkce = os.environ.get("META_USE_PKCE", "true").strip().lower() not in {"0", "false", "no"}
    config = MetaOAuthConfig(app_id, app_secret, api_version, redirect_uri, tuple(item.strip() for item in scopes.split(",") if item.strip()), use_pkce)
    _validate(config)

    vault_path = os.environ.get("OPEN_DATA_BRIDGE_VAULT_PATH", "").strip() or default_vault_path()
    vault = UserVault(vault_path)
    vault.set(
        "meta.app_config",
        json.dumps(
            {
                "app_id": config.app_id,
                "app_secret": config.app_secret,
                "api_version": config.api_version,
                "redirect_uri": config.redirect_uri,
                "scopes": list(config.scopes),
                "use_pkce": config.use_pkce,
            },
            separators=(",", ":"),
        ),
    )
    print(json.dumps({"saved": True, "vault_path": str(vault_path), "scopes": list(config.scopes), "secrets_in_response": False}))


if __name__ == "__main__":
    try:
        main()
    except (ValueError, VaultError) as exc:
        raise SystemExit(f"configuration failed: {exc}") from exc

