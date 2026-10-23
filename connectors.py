"""Provider adapter contracts for Open Data Bridge.

Adapters must use official provider APIs and receive credentials through a
future encrypted credential provider. This module intentionally contains no
OAuth clients, provider secrets, or private endpoint assumptions.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol


@dataclass(frozen=True)
class Field:
    id: str
    type: str
    role: str
    description: str = ""


@dataclass(frozen=True)
class Account:
    id: str
    name: str
    provider: str


class CredentialProvider(Protocol):
    def get_access_token(self, tenant_id: str, connector_id: str, account_id: str) -> str:
        """Return a short-lived provider token; never log or persist the value."""


class Connector(Protocol):
    connector_id: str

    def fields(self, account: Account) -> list[Field]:
        ...

    def query(self, account: Account, fields: list[str], options: dict[str, Any]) -> list[dict[str, Any]]:
        ...


class ConnectorRegistry:
    def __init__(self) -> None:
        self._items: dict[str, Connector] = {}

    def register(self, connector: Connector) -> None:
        if connector.connector_id in self._items:
            raise ValueError(f"connector already registered: {connector.connector_id}")
        self._items[connector.connector_id] = connector

    def get(self, connector_id: str) -> Connector:
        try:
            return self._items[connector_id]
        except KeyError as exc:
            raise KeyError(f"unknown connector: {connector_id}") from exc

    def ids(self) -> list[str]:
        return sorted(self._items)


class OfficialApiPolicy:
    """Central policy metadata used by future adapters."""

    def __init__(self, requests_per_minute: int = 60, max_retries: int = 3) -> None:
        self.requests_per_minute = requests_per_minute
        self.max_retries = max_retries

    def retryable_status(self, status: int) -> bool:
        return status == 429 or 500 <= status <= 599

