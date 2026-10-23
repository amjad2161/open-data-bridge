from __future__ import annotations

import ipaddress
import hashlib
import json
import os
import secrets
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs, urlparse

from bridge_catalog import (
    ContractError,
    capability_matrix,
    get_connect_info,
    get_custom_fields,
    get_fields,
    get_options,
    list_actions,
    list_accounts,
    list_connectors,
    query_data,
    to_csv,
)
from meta_oauth import MetaOAuthClient, MetaOAuthError
from meta_publish import MetaPublishClient, MetaPublishError, PublishPlan, normalize_publish_request
from oauth import OAuthStateStore


META_STATE = OAuthStateStore()
MAX_REQUEST_BYTES = 1_048_576
SERVER_VERSION = "0.5.0"
ACTION_PREVIEWS: dict[str, dict[str, Any]] = {}
PUBLISH_PREVIEWS: dict[str, dict[str, Any]] = {}
PUBLISH_PREVIEW_TTL_SECONDS = 600

ACTION_CATALOG: dict[str, dict[str, Any]] = {
    "create_social_post": {"category": "social", "risk": "external_write", "description": "Create a provider-side post draft"},
    "schedule_social_post": {"category": "social", "risk": "external_write", "description": "Schedule a provider-side social post"},
    "publish_social_post": {"category": "social", "risk": "external_write", "description": "Publish a social post immediately"},
    "create_ad_campaign": {"category": "advertising", "risk": "paid_media_write", "description": "Create a paid advertising campaign"},
    "pause_ad_campaign": {"category": "advertising", "risk": "paid_media_write", "description": "Pause an advertising campaign"},
}


def json_response(handler: BaseHTTPRequestHandler, status: int, payload: object) -> None:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    handler.send_header("Cache-Control", "no-store")
    handler.end_headers()
    handler.wfile.write(body)


def redirect_response(handler: BaseHTTPRequestHandler, location: str) -> None:
    handler.send_response(302)
    handler.send_header("Location", location)
    handler.send_header("Cache-Control", "no-store")
    handler.send_header("Content-Length", "0")
    handler.end_headers()


def is_loopback_host(host: str) -> bool:
    if host.lower() == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def meta_client() -> MetaOAuthClient:
    return MetaOAuthClient(state_store=META_STATE)


def _query_value(query: dict[str, list[str]], key: str, default: Any = None) -> Any:
    values = query.get(key)
    return values[0] if values else default


def _query_jsonish(query: dict[str, list[str]], key: str, default: Any = None) -> Any:
    value = _query_value(query, key, default)
    if value in (None, ""):
        return default
    if isinstance(value, str) and value[:1] in "[{":
        try:
            return json.loads(value)
        except json.JSONDecodeError as exc:
            raise ContractError(f"invalid_{key}") from exc
    return value


def query_options(query: dict[str, list[str]]) -> dict[str, Any]:
    options: dict[str, Any] = {}
    for key in ("date_preset", "date_from", "date_to", "page_size", "_max_rows", "cursor", "refresh_since", "refresh_interval"):
        value = _query_value(query, key)
        if value is not None:
            options[key] = value
    for key in ("select_accounts", "filters", "filter", "group_by", "breakdowns"):
        value = _query_jsonish(query, key)
        if value is not None:
            options[key] = value
    return options


def _error_code(error: str) -> int:
    if error in {"unknown_connector", "connector_not_available"}:
        return 404
    return 400


def _query_http(query: dict[str, list[str]]) -> tuple[int, dict[str, Any]]:
    connector = _query_value(query, "connector", "")
    fields_raw = _query_value(query, "fields", "")
    fields = [part.strip() for part in str(fields_raw).split(",") if part.strip()]
    try:
        result = query_data(connector, fields, query_options(query))
    except ContractError as exc:
        message = str(exc)
        if message.startswith("invalid_fields:"):
            unknown = [part for part in message.split(":", 1)[1].split(",") if part]
            return 400, {"error": "invalid_fields", "unknown": unknown}
        return _error_code(message), {"error": message}
    if _query_value(query, "include_provenance", "true").lower() in {"0", "false", "no"}:
        result.pop("provenance", None)
    return 200, result


def _redact(value: Any) -> Any:
    sensitive = ("token", "secret", "password", "authorization", "api_key", "access_key")
    if isinstance(value, dict):
        return {key: "[REDACTED]" if any(part in key.lower() for part in sensitive) else _redact(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_redact(item) for item in value]
    return value


def _preview_action(args: dict[str, Any]) -> dict[str, Any]:
    action_type = args.get("action_type")
    if action_type not in ACTION_CATALOG:
        raise ContractError("unsupported_action_type")
    connector = args.get("connector") or ""
    preview_id = uuid.uuid4().hex
    action = ACTION_CATALOG[action_type]
    preview = {
        "preview_id": preview_id,
        "action_type": action_type,
        "category": action["category"],
        "risk": action["risk"],
        "description": action["description"],
        "connector": connector,
        "account_id": args.get("account_id"),
        "payload": _redact(args.get("payload", {})),
        "requires_confirmation": True,
        "can_execute": False,
        "execution_status": "blocked",
        "blocked_reasons": [
            "writes_disabled",
            "provider_write_adapter_not_implemented",
            "live_account_authorization_required",
        ],
    }
    ACTION_PREVIEWS[preview_id] = preview
    return preview


def _execute_action(args: dict[str, Any]) -> dict[str, Any]:
    preview_id = args.get("preview_id")
    preview = ACTION_PREVIEWS.get(str(preview_id))
    if not preview:
        raise ContractError("unknown_preview")
    return {
        "preview_id": preview_id,
        "action_type": preview["action_type"],
        "executed": False,
        "status": "blocked",
        "reason": "writes_disabled",
        "side_effects": [],
        "confirmation_received": bool(args.get("confirmation_token")),
    }


def _destinations() -> dict[str, Any]:
    return {
        "destinations": [
            {"id": "local_json", "name": "Local JSON response", "status": "implemented_local", "write_supported": False},
            {"id": "local_csv", "name": "Local CSV export", "status": "implemented_local", "write_supported": False},
            {"id": "bigquery", "name": "BigQuery", "status": "not_implemented", "write_supported": False},
            {"id": "snowflake", "name": "Snowflake", "status": "not_implemented", "write_supported": False},
            {"id": "redshift", "name": "Amazon Redshift", "status": "not_implemented", "write_supported": False},
            {"id": "power_bi", "name": "Power BI", "status": "not_implemented", "write_supported": False},
            {"id": "looker_studio", "name": "Looker Studio", "status": "not_implemented", "write_supported": False},
            {"id": "tableau", "name": "Tableau", "status": "not_implemented", "write_supported": False},
        ],
        "sync_enabled": False,
        "reason": "destination adapters, scheduling and durable sync state are not implemented",
    }


def _destination_tasks() -> dict[str, Any]:
    return {
        "tasks": [],
        "count": 0,
        "sync_enabled": False,
        "reason": "durable scheduling and destination adapters are not implemented",
    }


def _destination_setup_info(destination: str) -> dict[str, Any]:
    known = {item["id"]: item for item in _destinations()["destinations"]}
    if destination not in known:
        raise ContractError("unknown_destination")
    return {
        "destination": destination,
        "name": known[destination]["name"],
        "status": known[destination]["status"],
        "target_fields": ["connector", "fields", "date_from", "date_to", "schedule"],
        "allowed_schedules": ["hourly", "daily", "weekly", "monthly"],
        "setup_url": None,
        "sensitive_fields_entered_in_form": True,
        "reason": "destination setup is local-contract only; no external writer is enabled",
    }


def _create_destination_task(args: dict[str, Any]) -> dict[str, Any]:
    return {
        "created": False,
        "status": "blocked",
        "side_effects": [],
        "reason": "writes_disabled_and_destination_adapters_not_implemented",
        "requested": _redact(args),
    }


def _sync_status() -> dict[str, Any]:
    return {
        "status": "not_configured",
        "active_jobs": [],
        "last_refresh": None,
        "refresh_supported": False,
        "reason": "local bridge uses deterministic synthetic data and has no provider sync scheduler",
    }


def _subscription_info() -> dict[str, Any]:
    return {
        "available": False,
        "url": None,
        "billing_enabled": False,
        "reason": "this local bridge has no subscription, payment wall or per-query credit system",
        "provider_limits_still_apply": True,
    }


def _login_info() -> dict[str, Any]:
    return {
        "authenticated": False,
        "url": None,
        "reason": "local single-user mode has no dashboard login",
    }


def _contact_info(args: dict[str, Any]) -> dict[str, Any]:
    return {
        "sent": False,
        "reference_id": None,
        "reason": "outbound support messaging is disabled; no external message was sent",
        "requested": _redact(args),
    }


def _create_custom_field(args: dict[str, Any]) -> dict[str, Any]:
    connector = args.get("connector")
    field_name = args.get("field_name")
    field_type = args.get("field_type")
    formula = args.get("formula")
    if not isinstance(connector, str) or not connector:
        raise ContractError("connector_required")
    if not isinstance(field_name, str) or not field_name or not field_name.replace("_", "").isalnum():
        raise ContractError("invalid_field_name")
    if field_type not in {"NUMERIC", "TEXT"}:
        raise ContractError("invalid_field_type")
    if not isinstance(formula, str) or not formula.strip():
        raise ContractError("formula_required")
    return {
        "created": False,
        "status": "blocked",
        "connector": connector,
        "field_name": field_name,
        "field_type": field_type,
        "formula": formula,
        "reason": "provider custom-field persistence is not implemented; no external mutation occurred",
    }


def publish_client() -> MetaPublishClient:
    return MetaPublishClient(oauth=meta_client())


def _publish_capabilities() -> dict[str, Any]:
    result = publish_client().capabilities()
    result["connection"] = meta_client().status()
    return result


def _meta_accounts() -> dict[str, Any]:
    return publish_client().stored_accounts()


def _sync_meta_accounts() -> dict[str, Any]:
    try:
        return publish_client().discover_accounts()
    except MetaPublishError as exc:
        return {
            "provider": "meta",
            "synced": False,
            "status": "blocked",
            "reason": exc.code,
            "secrets_in_response": False,
        }


def _publish_plan_digest(plan: PublishPlan) -> str:
    encoded = json.dumps(plan.public_dict(), ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _cleanup_publish_previews() -> None:
    cutoff = time.time() - PUBLISH_PREVIEW_TTL_SECONDS
    expired = [key for key, value in PUBLISH_PREVIEWS.items() if value.get("created_at", 0) < cutoff]
    for key in expired:
        PUBLISH_PREVIEWS.pop(key, None)


def _preview_publish(args: dict[str, Any]) -> dict[str, Any]:
    try:
        plan = normalize_publish_request(args)
    except MetaPublishError as exc:
        raise ContractError(exc.code) from exc
    _cleanup_publish_previews()
    preview_id = uuid.uuid4().hex
    PUBLISH_PREVIEWS[preview_id] = {
        "preview_id": preview_id,
        "created_at": time.time(),
        "plan": plan,
        "digest": _publish_plan_digest(plan),
        "approved": False,
        "consumed": False,
        "approval_token": secrets.token_urlsafe(32),
    }
    return {
        "preview_id": preview_id,
        "status": "awaiting_approval",
        "requires_explicit_approval": True,
        "approval_phrase": "PUBLISH_NOW",
        "expires_in_seconds": PUBLISH_PREVIEW_TTL_SECONDS,
        "plan": plan.public_dict(),
        "plan_sha256": _publish_plan_digest(plan),
        "external_side_effects": ["create_or_publish_provider_media"],
        "provider_token_in_response": False,
    }


def _publish_record(preview_id: Any) -> dict[str, Any]:
    _cleanup_publish_previews()
    record = PUBLISH_PREVIEWS.get(str(preview_id))
    if not record:
        raise ContractError("unknown_publish_preview")
    return record


def _approve_publish(args: dict[str, Any]) -> dict[str, Any]:
    record = _publish_record(args.get("preview_id"))
    if record["consumed"]:
        raise ContractError("publish_preview_already_consumed")
    if record["approved"]:
        raise ContractError("publish_preview_already_approved")
    if args.get("approval_phrase") != "PUBLISH_NOW":
        raise ContractError("explicit_publish_approval_required")
    record["approved"] = True
    record["approved_at"] = time.time()
    return {
        "preview_id": record["preview_id"],
        "approved": True,
        "status": "approved",
        "approval_token": record["approval_token"],
        "expires_in_seconds": PUBLISH_PREVIEW_TTL_SECONDS,
        "plan_sha256": record["digest"],
        "provider_token_in_response": False,
    }


def _execute_publish(args: dict[str, Any]) -> dict[str, Any]:
    record = _publish_record(args.get("preview_id"))
    plan: PublishPlan = record["plan"]
    if args.get("dry_run") is True:
        return {
            "preview_id": record["preview_id"],
            "status": "dry_run",
            "executed": False,
            "provider_request_made": False,
            "plan": plan.public_dict(),
            "plan_sha256": record["digest"],
        }
    if not record["approved"]:
        raise ContractError("publish_approval_required")
    token = args.get("approval_token")
    if not isinstance(token, str) or not secrets.compare_digest(token, record["approval_token"]):
        raise ContractError("invalid_publish_approval_token")
    if record["consumed"]:
        raise ContractError("publish_approval_already_consumed")
    # Consume before the provider call.  If the process or network fails after
    # the request starts, a retry could duplicate a real post, so the result is
    # reported as unknown and the caller must verify in Meta.
    record["consumed"] = True
    record["execution_started_at"] = time.time()
    try:
        result = publish_client().publish(plan)
    except MetaPublishError as exc:
        record["status"] = "unknown" if exc.side_effect_started else "blocked"
        return {
            "preview_id": record["preview_id"],
            "status": record["status"],
            "executed": False,
            "provider_request_made": exc.side_effect_started,
            "reason": exc.code,
            "retry_allowed": False,
            "verify_provider_before_retry": exc.side_effect_started,
            "side_effects": ["provider_request_started"] if exc.side_effect_started else [],
        }
    record["status"] = "published"
    return {
        "preview_id": record["preview_id"],
        "status": "published",
        "executed": True,
        "provider_request_made": True,
        "retry_allowed": False,
        "result": result,
    }


def _profile() -> dict[str, Any]:
    return {
        "authenticated": False,
        "mode": "local_single_user",
        "tenant_id": "local",
        "identity_source": "not_configured",
        "secrets_in_response": False,
        "note": "Public multi-user authentication is not enabled by this local bridge.",
    }


def tool_definitions() -> list[dict[str, Any]]:
    read = {"readOnlyHint": True, "destructiveHint": False, "openWorldHint": False}
    connect = {"readOnlyHint": False, "destructiveHint": False, "openWorldHint": True}
    write = {"readOnlyHint": False, "destructiveHint": True, "openWorldHint": True}
    return [
        {"name": "get_current_user", "description": "Return non-secret local identity and tenancy status", "inputSchema": {"type": "object", "properties": {}}, "annotations": read},
        {"name": "get_capabilities", "description": "Return implemented, partial, blocked and planned bridge capabilities", "inputSchema": {"type": "object", "properties": {}}, "annotations": read},
        {"name": "get_connectors", "description": "List active connectors or the full catalog with explicit implementation status", "inputSchema": {"type": "object", "properties": {"include_not_yet_connected": {"type": "boolean"}}}, "annotations": read},
        {"name": "get_connector_connect_info", "description": "Return account, scope and authorization requirements for a connector", "inputSchema": {"type": "object", "properties": {"connector": {"type": "string"}}, "required": ["connector"]}, "annotations": read},
        {"name": "get_connector_authorization_url", "description": "Create a provider authorization URL when the local provider flow is configured", "inputSchema": {"type": "object", "properties": {"connector": {"type": "string"}}, "required": ["connector"]}, "annotations": connect},
        {"name": "get_options", "description": "Return date presets, dimensions, metrics, filters and account options", "inputSchema": {"type": "object", "properties": {"connector": {"type": "string"}}, "required": ["connector"]}, "annotations": read},
        {"name": "get_fields", "description": "Return the connector field schema", "inputSchema": {"type": "object", "properties": {"connector": {"type": "string"}}, "required": ["connector"]}, "annotations": read},
        {"name": "get_custom_fields", "description": "Return calculated/custom field definitions", "inputSchema": {"type": "object", "properties": {"connector": {"type": "string"}}, "required": ["connector"]}, "annotations": read},
        {"name": "get_data", "description": "Query connector data with date presets, account selection, connector options, nested filters, breakdowns, pagination and refresh hints", "inputSchema": {"type": "object", "properties": {"connector": {"type": "string"}, "fields": {"type": "array", "items": {"type": "string"}}, "date_preset": {"type": "string"}, "date_from": {"type": "string"}, "date_to": {"type": "string"}, "select_accounts": {"type": "array", "items": {"type": "string"}}, "filters": {}, "filter": {}, "group_by": {"type": "array", "items": {"type": "string"}}, "breakdowns": {"type": "array", "items": {"type": "string"}}, "page_size": {"type": "integer"}, "_max_rows": {"type": "integer"}, "cursor": {"type": "string"}, "refresh_since": {"type": "string"}, "refresh_interval": {"type": "string"}, "include_provenance": {"type": "boolean"}}, "required": ["connector", "fields"]}, "annotations": read},
        {"name": "export_data", "description": "Run a read-only query and render its current page as JSON or CSV", "inputSchema": {"type": "object", "properties": {"connector": {"type": "string"}, "fields": {"type": "array", "items": {"type": "string"}}, "format": {"type": "string", "enum": ["json", "csv"]}, "date_preset": {"type": "string"}, "date_from": {"type": "string"}, "date_to": {"type": "string"}, "filters": {}, "filter": {}}, "required": ["connector", "fields"]}, "annotations": read},
        {"name": "get_destinations", "description": "Return local export and planned warehouse/BI destination capabilities", "inputSchema": {"type": "object", "properties": {}}, "annotations": read},
        {"name": "get_destination_tasks", "description": "List scheduled export tasks; local bridge currently has none", "inputSchema": {"type": "object", "properties": {}}, "annotations": read},
        {"name": "get_destination_setup_info", "description": "Describe destination setup requirements without collecting secrets in chat", "inputSchema": {"type": "object", "properties": {"destination": {"type": "string"}}, "required": ["destination"]}, "annotations": read},
        {"name": "create_destination_task", "description": "Create a recurring export task; currently fail-closed because writers and scheduling are disabled", "inputSchema": {"type": "object", "properties": {"destination": {"type": "string"}, "connector": {"type": "string"}, "fields": {"type": "array", "items": {"type": "string"}}, "schedule": {"type": "string"}}, "required": ["destination", "connector", "fields", "schedule"]}, "annotations": write},
        {"name": "get_accounts", "description": "List connected accounts with explicit synthetic/provider status", "inputSchema": {"type": "object", "properties": {"connector": {"type": "string"}}}, "annotations": read},
        {"name": "get_sync_status", "description": "Return refresh and synchronization status without claiming provider sync", "inputSchema": {"type": "object", "properties": {}}, "annotations": read},
        {"name": "get_subscription_url", "description": "Return billing status; local bridge has no subscription or credit wall", "inputSchema": {"type": "object", "properties": {"target_plan": {"type": "string"}}}, "annotations": read},
        {"name": "get_windsor_login_url", "description": "Return a dashboard login link when configured; local bridge has no dashboard login", "inputSchema": {"type": "object", "properties": {"page": {"type": "string"}}}, "annotations": connect},
        {"name": "contact_windsor", "description": "Prepare support feedback without sending outbound messages", "inputSchema": {"type": "object", "properties": {"kind": {"type": "string"}, "message": {"type": "string"}}, "required": ["kind", "message"]}, "annotations": connect},
        {"name": "list_actions", "description": "Discover connector write actions and their JSON schemas; execution remains disabled", "inputSchema": {"type": "object", "properties": {"connector": {"type": "string"}}, "required": ["connector"]}, "annotations": read},
        {"name": "create_custom_field", "description": "Validate a custom field request without persisting provider-side changes", "inputSchema": {"type": "object", "properties": {"connector": {"type": "string"}, "field_name": {"type": "string"}, "field_type": {"type": "string", "enum": ["NUMERIC", "TEXT"]}, "formula": {"type": "string"}}, "required": ["connector", "field_name", "field_type", "formula"]}, "annotations": write},
        {"name": "preview_action", "description": "Create a non-executing, redacted preview for a publishing or advertising action", "inputSchema": {"type": "object", "properties": {"action_type": {"type": "string"}, "connector": {"type": "string"}, "account_id": {"type": "string"}, "payload": {"type": "object"}}, "required": ["action_type"]}, "annotations": read},
        {"name": "execute_action", "description": "Attempt an explicitly confirmed action; currently fail-closed because writes are disabled", "inputSchema": {"type": "object", "properties": {"preview_id": {"type": "string"}, "confirmation_token": {"type": "string"}}, "required": ["preview_id"]}, "annotations": write},
        {"name": "get_meta_connect_url", "description": "Compatibility alias for Meta authorization URL", "inputSchema": {"type": "object", "properties": {}}, "annotations": connect},
        {"name": "get_meta_connection_status", "description": "Return non-secret Meta connection status", "inputSchema": {"type": "object", "properties": {}}, "annotations": read},
        {"name": "get_publish_capabilities", "description": "Return the verified Meta publishing surface, required permissions and provider limits", "inputSchema": {"type": "object", "properties": {}}, "annotations": read},
        {"name": "get_meta_accounts", "description": "List locally discovered Meta Pages and connected Instagram professional accounts without secrets", "inputSchema": {"type": "object", "properties": {}}, "annotations": read},
        {"name": "sync_meta_accounts", "description": "Discover Meta Pages and connected Instagram accounts; page tokens are stored only in the local encrypted vault", "inputSchema": {"type": "object", "properties": {}}, "annotations": connect},
        {"name": "preview_publish", "description": "Validate and preview a Facebook or Instagram post without contacting the provider", "inputSchema": {"type": "object", "properties": {"channel": {"type": "string", "enum": ["facebook_page", "instagram"]}, "account_id": {"type": "string"}, "media_type": {"type": "string", "enum": ["text", "link", "image", "video", "reel"]}, "caption": {"type": "string"}, "media_url": {"type": "string"}, "link": {"type": "string"}, "alt_text": {"type": "string"}, "is_ai_generated": {"type": "boolean"}, "scheduled_publish_time": {}}, "required": ["channel", "account_id", "media_type"]}, "annotations": read},
        {"name": "approve_publish", "description": "Approve one exact publish preview using the explicit PUBLISH_NOW phrase; this does not contact Meta", "inputSchema": {"type": "object", "properties": {"preview_id": {"type": "string"}, "approval_phrase": {"type": "string"}}, "required": ["preview_id", "approval_phrase"]}, "annotations": write},
        {"name": "publish_media", "description": "Execute one previously approved Facebook or Instagram publish plan; the approval grant is one-time and provider limits apply", "inputSchema": {"type": "object", "properties": {"preview_id": {"type": "string"}, "approval_token": {"type": "string"}, "dry_run": {"type": "boolean"}}, "required": ["preview_id"]}, "annotations": write},
    ]


class Handler(BaseHTTPRequestHandler):
    server_version = "OpenDataBridge/" + SERVER_VERSION

    def log_message(self, *_args: object) -> None:
        return

    def _authorization_failure(self, path: str) -> tuple[int, dict[str, str]] | None:
        if path in {"/health", "/oauth/meta/callback"}:
            return None
        bound_host = str(self.server.server_address[0])
        shared_secret = os.environ.get("OPEN_DATA_BRIDGE_SHARED_SECRET", "").strip()
        if not is_loopback_host(bound_host) and not shared_secret:
            return 503, {"error": "public_bind_requires_shared_secret"}
        if not shared_secret:
            return None
        expected = f"Bearer {shared_secret}"
        if self.headers.get("Authorization", "") != expected:
            return 401, {"error": "unauthorized"}
        return None

    def _check_authorization(self, path: str) -> bool:
        failure = self._authorization_failure(path)
        if failure is None:
            return True
        status, payload = failure
        if status == 401:
            self.send_response(status)
            self.send_header("WWW-Authenticate", 'Bearer realm="open-data-bridge"')
            self.send_header("Content-Type", "application/json; charset=utf-8")
            body = json.dumps(payload).encode("utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)
        else:
            json_response(self, status, payload)
        return False

    def _read_json(self) -> dict[str, Any] | None:
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length < 0 or length > MAX_REQUEST_BYTES:
                return None
            value = json.loads(self.rfile.read(length) or b"{}")
        except (ValueError, json.JSONDecodeError):
            return None
        return value if isinstance(value, dict) else None

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        if not self._check_authorization(parsed.path):
            return
        query = parse_qs(parsed.query)
        if parsed.path == "/health":
            return json_response(self, 200, {"status": "ok", "mode": "local", "version": SERVER_VERSION, "writes_enabled": False, "catalog_count": len(list_connectors(True))})
        if parsed.path == "/api/profile":
            return json_response(self, 200, _profile())
        if parsed.path == "/api/capabilities":
            return json_response(self, 200, capability_matrix())
        if parsed.path == "/api/destinations":
            return json_response(self, 200, _destinations())
        if parsed.path == "/api/destinations/tasks":
            return json_response(self, 200, _destination_tasks())
        if parsed.path == "/api/destinations/setup-info":
            try:
                return json_response(self, 200, _destination_setup_info(str(_query_value(query, "destination", ""))))
            except ContractError as exc:
                return json_response(self, 404, {"error": str(exc)})
        if parsed.path == "/api/accounts":
            try:
                return json_response(self, 200, list_accounts(_query_value(query, "connector", None)))
            except ContractError as exc:
                return json_response(self, _error_code(str(exc)), {"error": str(exc)})
        if parsed.path == "/api/actions":
            try:
                return json_response(self, 200, list_actions(str(_query_value(query, "connector", ""))))
            except ContractError as exc:
                return json_response(self, _error_code(str(exc)), {"error": str(exc)})
        if parsed.path == "/api/sync/status":
            return json_response(self, 200, _sync_status())
        if parsed.path == "/api/subscription-url":
            return json_response(self, 200, _subscription_info())
        if parsed.path == "/api/login-url":
            return json_response(self, 200, _login_info())
        if parsed.path == "/api/connectors":
            include = str(_query_value(query, "include_not_yet_connected", "false")).lower() in {"1", "true", "yes"}
            return json_response(self, 200, {"data": list_connectors(include)})
        if parsed.path == "/api/fields":
            try:
                result = get_fields(_query_value(query, "connector", ""))
            except ContractError as exc:
                return json_response(self, _error_code(str(exc)), {"error": str(exc)})
            return json_response(self, 200, result)
        if parsed.path == "/api/options":
            try:
                result = get_options(_query_value(query, "connector", ""))
            except ContractError as exc:
                return json_response(self, _error_code(str(exc)), {"error": str(exc)})
            return json_response(self, 200, result)
        if parsed.path == "/api/custom-fields":
            try:
                result = get_custom_fields(_query_value(query, "connector", ""))
            except ContractError as exc:
                return json_response(self, _error_code(str(exc)), {"error": str(exc)})
            return json_response(self, 200, result)
        if parsed.path == "/api/connect-info":
            try:
                result = get_connect_info(_query_value(query, "connector", ""))
            except ContractError as exc:
                return json_response(self, _error_code(str(exc)), {"error": str(exc)})
            return json_response(self, 200, result)
        if parsed.path == "/api/data":
            status, result = _query_http(query)
            return json_response(self, status, result)
        if parsed.path == "/api/export":
            status, result = _query_http(query)
            if status != 200:
                return json_response(self, status, result)
            output_format = str(_query_value(query, "format", "json")).lower()
            if output_format == "csv":
                return json_response(self, 200, {"format": "csv", "content_type": "text/csv", "content": to_csv(result), "count": result["count"], "query": result["query"]})
            if output_format != "json":
                return json_response(self, 400, {"error": "invalid_format"})
            return json_response(self, 200, {"format": "json", "content_type": "application/json", "content": result})
        if parsed.path == "/api/meta/status":
            return json_response(self, 200, meta_client().status())
        if parsed.path == "/api/publish/capabilities":
            try:
                return json_response(self, 200, _publish_capabilities())
            except MetaPublishError as exc:
                return json_response(self, 503, {"error": exc.code})
        if parsed.path == "/api/meta/accounts":
            try:
                return json_response(self, 200, _meta_accounts())
            except MetaPublishError as exc:
                return json_response(self, 503, {"error": exc.code})
        if parsed.path == "/api/meta/connect-url":
            return self._meta_authorization_json()
        if parsed.path == "/oauth/meta/start":
            return self._meta_authorization_redirect()
        if parsed.path == "/oauth/meta/callback":
            if query.get("error"):
                return json_response(self, 400, {"error": "meta_authorization_denied"})
            state = _query_value(query, "state", "")
            code = _query_value(query, "code", "")
            try:
                result = meta_client().complete(state, code)
            except MetaOAuthError as exc:
                return json_response(self, 400, {"error": str(exc)})
            return json_response(self, 200, result)
        if parsed.path == "/mcp/tools":
            return json_response(self, 200, {"tools": tool_definitions()})
        return json_response(self, 404, {"error": "not_found"})

    def _meta_authorization_json(self) -> None:
        try:
            _item, url = meta_client().start()
        except MetaOAuthError as exc:
            return json_response(self, 503, {"error": "meta_oauth_not_ready", "detail": str(exc)})
        return json_response(self, 200, {"provider": "meta", "authorization_url": url})

    def _meta_authorization_redirect(self) -> None:
        try:
            _item, url = meta_client().start()
        except MetaOAuthError as exc:
            return json_response(self, 503, {"error": "meta_oauth_not_ready", "detail": str(exc)})
        return redirect_response(self, url)

    def do_POST(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        if not self._check_authorization(parsed.path):
            return
        if parsed.path == "/api/actions/preview":
            body = self._read_json()
            if body is None:
                return json_response(self, 400, {"error": "invalid_json"})
            try:
                return json_response(self, 200, _preview_action(body))
            except ContractError as exc:
                return json_response(self, 400, {"error": str(exc)})
        if parsed.path == "/api/actions/execute":
            body = self._read_json()
            if body is None:
                return json_response(self, 400, {"error": "invalid_json"})
            try:
                return json_response(self, 409, _execute_action(body))
            except ContractError as exc:
                return json_response(self, 400, {"error": str(exc)})
        if parsed.path == "/api/meta/accounts/sync":
            return json_response(self, 200, _sync_meta_accounts())
        if parsed.path == "/api/publish/preview":
            body = self._read_json()
            if body is None:
                return json_response(self, 400, {"error": "invalid_json"})
            try:
                return json_response(self, 200, _preview_publish(body))
            except ContractError as exc:
                return json_response(self, 400, {"error": str(exc)})
        if parsed.path == "/api/publish/approve":
            body = self._read_json()
            if body is None:
                return json_response(self, 400, {"error": "invalid_json"})
            try:
                return json_response(self, 200, _approve_publish(body))
            except ContractError as exc:
                return json_response(self, 400, {"error": str(exc)})
        if parsed.path == "/api/publish/execute":
            body = self._read_json()
            if body is None:
                return json_response(self, 400, {"error": "invalid_json"})
            try:
                result = _execute_publish(body)
                http_status = 200 if result.get("status") in {"published", "dry_run"} else 409
                return json_response(self, http_status, result)
            except ContractError as exc:
                return json_response(self, 400, {"error": str(exc)})
        if parsed.path == "/api/destinations/tasks":
            body = self._read_json()
            if body is None:
                return json_response(self, 400, {"error": "invalid_json"})
            return json_response(self, 409, _create_destination_task(body))
        if parsed.path == "/api/custom-fields":
            body = self._read_json()
            if body is None:
                return json_response(self, 400, {"error": "invalid_json"})
            try:
                return json_response(self, 409, _create_custom_field(body))
            except ContractError as exc:
                return json_response(self, 400, {"error": str(exc)})
        if parsed.path == "/api/contact":
            body = self._read_json()
            if body is None:
                return json_response(self, 400, {"error": "invalid_json"})
            return json_response(self, 409, _contact_info(body))
        if parsed.path != "/mcp":
            return json_response(self, 404, {"error": "not_found"})
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length < 0 or length > MAX_REQUEST_BYTES:
                return json_response(self, 413, {"jsonrpc": "2.0", "id": None, "error": {"code": -32000, "message": "request too large"}})
            request = json.loads(self.rfile.read(length) or b"{}")
        except (ValueError, json.JSONDecodeError):
            return json_response(self, 400, {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "Parse error"}})
        if not isinstance(request, dict):
            return json_response(self, 400, {"jsonrpc": "2.0", "id": None, "error": {"code": -32600, "message": "Invalid Request"}})
        method = request.get("method")
        request_id = request.get("id")
        params = request.get("params", {})
        if params is None:
            params = {}
        if not isinstance(params, dict):
            return self._mcp_error(request_id, -32602, "invalid params")
        if method == "initialize":
            return json_response(self, 200, {"jsonrpc": "2.0", "id": request_id, "result": {"protocolVersion": params.get("protocolVersion", "2025-03-26"), "capabilities": {"tools": {}}, "serverInfo": {"name": "open-data-bridge", "version": SERVER_VERSION}, "instructions": "Use read tools for connector discovery and queries. For Meta publishing, first call preview_publish, then obtain explicit approval with approve_publish using PUBLISH_NOW, then call publish_media once. Do not retry an unknown provider outcome; verify in Meta. Meta OAuth, account permissions and provider limits remain required."}})
        if method == "notifications/initialized":
            return json_response(self, 200, {"jsonrpc": "2.0", "id": request_id, "result": {}})
        if method == "tools/list":
            return json_response(self, 200, {"jsonrpc": "2.0", "id": request_id, "result": {"tools": tool_definitions()}})
        if method == "tools/call":
            return self.mcp_call(request_id, params)
        return self._mcp_error(request_id, -32601, "Method not found")

    def _mcp_error(self, request_id: object, code: int, message: str) -> None:
        return json_response(self, 200, {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}})

    def _mcp_result(self, request_id: object, result: Any, is_error: bool = False) -> None:
        payload: dict[str, Any] = {"content": [{"type": "text", "text": json.dumps(result, ensure_ascii=False)}], "structuredContent": result}
        if is_error:
            payload["isError"] = True
        return json_response(self, 200, {"jsonrpc": "2.0", "id": request_id, "result": payload})

    def mcp_call(self, request_id: object, params: dict[str, Any]) -> None:
        name = params.get("name")
        args = params.get("arguments", {})
        if not isinstance(args, dict):
            return self._mcp_error(request_id, -32602, "invalid arguments")
        try:
            if name == "get_current_user":
                return self._mcp_result(request_id, _profile())
            if name == "get_capabilities":
                return self._mcp_result(request_id, capability_matrix())
            if name == "get_connectors":
                return self._mcp_result(request_id, {"data": list_connectors(bool(args.get("include_not_yet_connected", False)))})
            if name == "get_connector_connect_info":
                return self._mcp_result(request_id, get_connect_info(str(args.get("connector", ""))))
            if name == "get_connector_authorization_url":
                connector = str(args.get("connector", ""))
                info = get_connect_info(connector)
                if info["authorization_supported"]:
                    _item, url = meta_client().start()
                    return self._mcp_result(request_id, {"connector": connector, "provider": "meta", "authorization_url": url, "expires_in_seconds": 600})
                return self._mcp_result(request_id, {"connector": connector, "authorization_supported": False, "status": "not_configured", "required_scopes": info["required_scopes"]})
            if name == "get_options":
                return self._mcp_result(request_id, get_options(str(args.get("connector", ""))))
            if name == "get_fields":
                return self._mcp_result(request_id, get_fields(str(args.get("connector", ""))))
            if name == "get_custom_fields":
                return self._mcp_result(request_id, get_custom_fields(str(args.get("connector", ""))))
            if name == "get_data":
                connector = args.get("connector", "")
                fields = args.get("fields", [])
                if not isinstance(connector, str) or not isinstance(fields, list) or not fields or not all(isinstance(field, str) for field in fields):
                    raise ContractError("invalid_data_arguments")
                options = {key: args[key] for key in ("date_preset", "date_from", "date_to", "select_accounts", "filters", "filter", "group_by", "breakdowns", "page_size", "_max_rows", "cursor", "refresh_since", "refresh_interval") if key in args}
                result = query_data(connector, fields, options)
                if args.get("include_provenance") is False:
                    result.pop("provenance", None)
                return self._mcp_result(request_id, result)
            if name == "export_data":
                connector = args.get("connector", "")
                fields = args.get("fields", [])
                if not isinstance(fields, list):
                    raise ContractError("invalid_data_arguments")
                options = {key: args[key] for key in ("date_preset", "date_from", "date_to", "select_accounts", "filters", "filter", "group_by", "breakdowns", "page_size", "_max_rows", "cursor", "refresh_since", "refresh_interval") if key in args}
                result = query_data(connector, fields, options)
                output_format = str(args.get("format", "json")).lower()
                if output_format == "csv":
                    return self._mcp_result(request_id, {"format": "csv", "content_type": "text/csv", "content": to_csv(result), "count": result["count"], "query": result["query"]})
                if output_format != "json":
                    raise ContractError("invalid_format")
                return self._mcp_result(request_id, {"format": "json", "content_type": "application/json", "content": result})
            if name == "get_destinations":
                return self._mcp_result(request_id, _destinations())
            if name == "get_destination_tasks":
                return self._mcp_result(request_id, _destination_tasks())
            if name == "get_destination_setup_info":
                return self._mcp_result(request_id, _destination_setup_info(str(args.get("destination", ""))))
            if name == "create_destination_task":
                return self._mcp_result(request_id, _create_destination_task(args), is_error=True)
            if name == "get_accounts":
                return self._mcp_result(request_id, list_accounts(args.get("connector")))
            if name == "get_sync_status":
                return self._mcp_result(request_id, _sync_status())
            if name == "get_subscription_url":
                return self._mcp_result(request_id, _subscription_info())
            if name == "get_windsor_login_url":
                return self._mcp_result(request_id, _login_info())
            if name == "contact_windsor":
                return self._mcp_result(request_id, _contact_info(args), is_error=True)
            if name == "list_actions":
                return self._mcp_result(request_id, list_actions(str(args.get("connector", ""))))
            if name == "create_custom_field":
                return self._mcp_result(request_id, _create_custom_field(args), is_error=True)
            if name == "preview_action":
                return self._mcp_result(request_id, _preview_action(args))
            if name == "execute_action":
                return self._mcp_result(request_id, _execute_action(args), is_error=True)
            if name == "get_meta_connect_url":
                _item, url = meta_client().start()
                return self._mcp_result(request_id, {"provider": "meta", "authorization_url": url})
            if name == "get_meta_connection_status":
                return self._mcp_result(request_id, meta_client().status())
            if name == "get_publish_capabilities":
                return self._mcp_result(request_id, _publish_capabilities())
            if name == "get_meta_accounts":
                return self._mcp_result(request_id, _meta_accounts())
            if name == "sync_meta_accounts":
                result = _sync_meta_accounts()
                return self._mcp_result(request_id, result, is_error=not result.get("synced", False))
            if name == "preview_publish":
                return self._mcp_result(request_id, _preview_publish(args))
            if name == "approve_publish":
                return self._mcp_result(request_id, _approve_publish(args))
            if name == "publish_media":
                result = _execute_publish(args)
                return self._mcp_result(request_id, result, is_error=result.get("status") != "published" and not args.get("dry_run", False))
            return self._mcp_error(request_id, -32602, "unknown tool")
        except MetaOAuthError:
            return self._mcp_error(request_id, -32000, "provider authorization is not configured")
        except MetaPublishError as exc:
            return self._mcp_error(request_id, -32000, exc.code)
        except ContractError as exc:
            return self._mcp_error(request_id, -32602, str(exc))


def main() -> None:
    host = os.environ.get("OPEN_DATA_BRIDGE_HOST", "127.0.0.1")
    port = int(os.environ.get("OPEN_DATA_BRIDGE_PORT", "8788"))
    if not is_loopback_host(host) and not os.environ.get("OPEN_DATA_BRIDGE_SHARED_SECRET", "").strip():
        raise SystemExit("Refusing non-loopback bind without OPEN_DATA_BRIDGE_SHARED_SECRET")
    server = ThreadingHTTPServer((host, port), Handler)
    print(f"Open Data Bridge listening on http://{host}:{port}")
    server.serve_forever()


if __name__ == "__main__":
    main()

