"""Provider-specific Meta OAuth flow for the local bridge.

This module is intentionally disabled until the operator supplies a Meta app,
redirect URI, API version and explicit scopes through environment variables.
It never stores an app secret in source control and never returns access tokens
to HTTP or MCP callers.
"""

from __future__ import annotations

import json
import os
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlparse
from urllib.request import Request, urlopen

from oauth import OAuthStateStore, PendingAuthorization, pkce_challenge
from vault import UserVault, VaultError


class MetaOAuthError(RuntimeError):
    """A safe, non-secret error suitable for a user-facing response."""


@dataclass(frozen=True)
class MetaOAuthConfig:
    app_id: str
    app_secret: str
    api_version: str
    redirect_uri: str
    scopes: tuple[str, ...]
    use_pkce: bool = True

    @classmethod
    def from_env(cls) -> "MetaOAuthConfig":
        scopes = tuple(
            item.strip()
            for item in os.environ.get("META_OAUTH_SCOPES", "").split(",")
            if item.strip()
        )
        value = cls(
            app_id=os.environ.get("META_APP_ID", "").strip(),
            app_secret=os.environ.get("META_APP_SECRET", "").strip(),
            api_version=os.environ.get("META_API_VERSION", "").strip(),
            redirect_uri=os.environ.get("META_REDIRECT_URI", "").strip(),
            scopes=scopes,
            use_pkce=os.environ.get("META_USE_PKCE", "true").strip().lower() not in {"0", "false", "no"},
        )
        return value

    @property
    def missing(self) -> list[str]:
        required = {
            "META_APP_ID": self.app_id,
            "META_APP_SECRET": self.app_secret,
            "META_API_VERSION": self.api_version,
            "META_REDIRECT_URI": self.redirect_uri,
            "META_OAUTH_SCOPES": self.scopes,
        }
        return [name for name, configured in required.items() if not configured]

    @property
    def configured(self) -> bool:
        return not self.missing

    @property
    def authorization_endpoint(self) -> str:
        return f"https://www.facebook.com/{self.api_version}/dialog/oauth"

    @property
    def token_endpoint(self) -> str:
        return f"https://graph.facebook.com/{self.api_version}/oauth/access_token"


def default_vault_path() -> Path:
    local_app_data = os.environ.get("LOCALAPPDATA", "").strip()
    if local_app_data:
        return Path(local_app_data) / "OpenDataBridge" / "vault.json"
    return Path.home() / ".open-data-bridge" / "vault.json"


class MetaOAuthClient:
    def __init__(
        self,
        config: MetaOAuthConfig | None = None,
        state_store: OAuthStateStore | None = None,
        vault: UserVault | None = None,
        opener: Callable[..., Any] | None = None,
    ) -> None:
        self.config = config or MetaOAuthConfig.from_env()
        self.state_store = state_store or OAuthStateStore()
        self.vault = vault or UserVault(os.environ.get("OPEN_DATA_BRIDGE_VAULT_PATH", "").strip() or default_vault_path())
        self._opener = opener or urlopen

    def _require_configured(self) -> None:
        if not self.config.configured:
            missing = ", ".join(self.config.missing)
            raise MetaOAuthError(f"meta_oauth_not_configured: missing {missing}")
        if not re.fullmatch(r"v\d+\.\d+", self.config.api_version):
            raise MetaOAuthError("meta_oauth_invalid_api_version")
        parsed_redirect = urlparse(self.config.redirect_uri)
        if parsed_redirect.fragment or not parsed_redirect.netloc:
            raise MetaOAuthError("meta_oauth_invalid_redirect_uri")
        if parsed_redirect.scheme == "https":
            return
        if parsed_redirect.scheme == "http" and parsed_redirect.hostname in {"127.0.0.1", "localhost", "::1"}:
            return
        raise MetaOAuthError("meta_oauth_redirect_requires_https")

    def start(self) -> tuple[PendingAuthorization, str]:
        self._require_configured()
        item = self.state_store.create("meta")
        params = {
            "client_id": self.config.app_id,
            "redirect_uri": self.config.redirect_uri,
            "response_type": "code",
            "state": item.state,
            "scope": ",".join(self.config.scopes),
        }
        if self.config.use_pkce:
            params["code_challenge"] = pkce_challenge(item.verifier)
            params["code_challenge_method"] = "S256"
        return item, self.config.authorization_endpoint + "?" + urlencode(params)

    def complete(self, state: str, code: str) -> dict[str, Any]:
        self._require_configured()
        if not state or not code:
            raise MetaOAuthError("meta_oauth_invalid_callback")
        try:
            item = self.state_store.consume(state)
            token_payload = self._exchange_code(item, code)
            access_token = token_payload.get("access_token")
            if not isinstance(access_token, str) or not access_token:
                raise MetaOAuthError("meta_oauth_missing_access_token")
            stored = {
                "access_token": access_token,
                "token_type": token_payload.get("token_type", "bearer"),
                "expires_in": token_payload.get("expires_in"),
                "stored_at": time.time(),
            }
            self.vault.set("meta.oauth", json.dumps(stored, separators=(",", ":")))
            return {"connected": True, "expires_in": stored["expires_in"]}
        except (ValueError, VaultError) as exc:
            raise MetaOAuthError("meta_oauth_state_or_storage_failed") from exc

    def _exchange_code(self, item: PendingAuthorization, code: str) -> dict[str, Any]:
        payload = {
            "client_id": self.config.app_id,
            "client_secret": self.config.app_secret,
            "redirect_uri": self.config.redirect_uri,
            "code": code,
        }
        if self.config.use_pkce:
            payload["code_verifier"] = item.verifier
        request = Request(
            self.config.token_endpoint,
            data=urlencode(payload).encode("utf-8"),
            headers={"Accept": "application/json", "Content-Type": "application/x-www-form-urlencoded"},
            method="POST",
        )
        try:
            with self._opener(request, timeout=20) as response:
                raw = response.read(1_048_576)
        except (HTTPError, URLError, TimeoutError, OSError) as exc:
            raise MetaOAuthError("meta_oauth_token_exchange_failed") from exc
        try:
            value = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise MetaOAuthError("meta_oauth_invalid_token_response") from exc
        if not isinstance(value, dict):
            raise MetaOAuthError("meta_oauth_invalid_token_response")
        if "error" in value:
            raise MetaOAuthError("meta_oauth_provider_rejected_code")
        return value

    def status(self) -> dict[str, Any]:
        try:
            raw = self.vault.get("meta.oauth")
        except VaultError:
            return {"provider": "meta", "connected": False, "storage_error": True}
        if not raw:
            return {"provider": "meta", "connected": False}
        try:
            value = json.loads(raw)
        except json.JSONDecodeError:
            return {"provider": "meta", "connected": False, "storage_error": True}
        expires_in = value.get("expires_in")
        stored_at = value.get("stored_at")
        expires_at = None
        if isinstance(expires_in, (int, float)) and isinstance(stored_at, (int, float)):
            expires_at = stored_at + expires_in
        return {
            "provider": "meta",
            "connected": True,
            "expires_at": expires_at,
            "expired": bool(expires_at is not None and time.time() >= expires_at),
        }

    def access_token_for_internal_use(self) -> str:
        """Return the encrypted token only to an in-process provider adapter.

        This is deliberately not used by HTTP/MCP response code.  Keeping the
        credential boundary here prevents individual adapters from inventing
        their own vault parsing and makes it possible to audit every provider
        call for token leakage.
        """
        try:
            raw = self.vault.get("meta.oauth")
        except VaultError as exc:
            raise MetaOAuthError("meta_oauth_storage_failed") from exc
        if not raw:
            raise MetaOAuthError("meta_oauth_not_connected")
        try:
            value = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise MetaOAuthError("meta_oauth_storage_invalid") from exc
        token = value.get("access_token")
        if not isinstance(token, str) or not token:
            raise MetaOAuthError("meta_oauth_missing_access_token")
        expires_in = value.get("expires_in")
        stored_at = value.get("stored_at")
        if isinstance(expires_in, (int, float)) and isinstance(stored_at, (int, float)):
            if time.time() >= stored_at + expires_in:
                raise MetaOAuthError("meta_oauth_token_expired")
        return token

    def disconnect(self) -> None:
        try:
            self.vault.delete("meta.oauth")
        except VaultError as exc:
            raise MetaOAuthError("meta_oauth_storage_failed") from exc

