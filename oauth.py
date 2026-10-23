"""Provider-neutral OAuth state/PKCE primitives.

This module does not contain provider client IDs, secrets, redirect calls, or
token exchange code. Provider adapters must supply their official endpoints and
scopes explicitly.
"""

from __future__ import annotations

import base64
import hashlib
import secrets
import time
from dataclasses import dataclass
from urllib.parse import urlencode


@dataclass
class PendingAuthorization:
    state: str
    verifier: str
    connector_id: str
    created_at: float
    expires_in: int = 600
    used: bool = False

    def valid(self, now: float | None = None) -> bool:
        current = time.time() if now is None else now
        return not self.used and current < self.created_at + self.expires_in


class OAuthStateStore:
    def __init__(self) -> None:
        self._items: dict[str, PendingAuthorization] = {}

    def create(self, connector_id: str, now: float | None = None) -> PendingAuthorization:
        created_at = time.time() if now is None else now
        state = secrets.token_urlsafe(32)
        verifier = secrets.token_urlsafe(64)
        item = PendingAuthorization(state, verifier, connector_id, created_at)
        self._items[state] = item
        return item

    def consume(self, state: str, now: float | None = None) -> PendingAuthorization:
        item = self._items.get(state)
        if item is None or not item.valid(now):
            raise ValueError("invalid or expired OAuth state")
        item.used = True
        return item

    def purge_expired(self, now: float | None = None) -> int:
        current = time.time() if now is None else now
        expired = [state for state, item in self._items.items() if not item.valid(current)]
        for state in expired:
            del self._items[state]
        return len(expired)


def pkce_challenge(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


def authorization_url(endpoint: str, client_id: str, redirect_uri: str, item: PendingAuthorization, scopes: list[str]) -> str:
    params = {
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "scope": " ".join(scopes),
        "state": item.state,
        "code_challenge": pkce_challenge(item.verifier),
        "code_challenge_method": "S256",
    }
    return endpoint + ("&" if "?" in endpoint else "?") + urlencode(params)

