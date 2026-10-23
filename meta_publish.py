"""Approval-gated Meta publishing adapter.

The adapter implements only provider contracts that have been verified against
Meta's current documentation:

* Facebook Pages: text/link posts and photo posts.
* Instagram professional accounts connected through Facebook Login: image
  posts and video/Reels posts when the media is hosted at a public HTTPS URL.

No access token is accepted from HTTP/MCP arguments, placed in a URL, logged,
or returned to callers.  Provider writes are intentionally performed only by
the application layer after its one-time approval record has been consumed.
"""

from __future__ import annotations

import ipaddress
import json
import os
import re
import time
from dataclasses import dataclass
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlparse
from urllib.request import Request, urlopen

from meta_oauth import MetaOAuthClient, MetaOAuthError
from vault import UserVault, VaultError


class MetaPublishError(RuntimeError):
    """Safe provider error with no credential material in its message."""

    def __init__(self, code: str, *, side_effect_started: bool = False) -> None:
        super().__init__(code)
        self.code = code
        self.side_effect_started = side_effect_started


@dataclass(frozen=True)
class PublishPlan:
    channel: str
    account_id: str
    media_type: str
    caption: str
    media_url: str | None = None
    link: str | None = None
    alt_text: str | None = None
    is_ai_generated: bool = False
    scheduled_publish_time: int | str | None = None

    def public_dict(self) -> dict[str, Any]:
        value: dict[str, Any] = {
            "channel": self.channel,
            "account_id": self.account_id,
            "media_type": self.media_type,
            "caption": self.caption,
            "is_ai_generated": self.is_ai_generated,
        }
        if self.media_url is not None:
            value["media_url"] = self.media_url
        if self.link is not None:
            value["link"] = self.link
        if self.alt_text is not None:
            value["alt_text"] = self.alt_text
        if self.scheduled_publish_time is not None:
            value["scheduled_publish_time"] = self.scheduled_publish_time
        return value


def _text(value: Any, field: str, *, required: bool = False, maximum: int = 10_000) -> str | None:
    if value is None and not required:
        return None
    if not isinstance(value, str):
        raise MetaPublishError(f"invalid_{field}")
    value = value.strip()
    if required and not value:
        raise MetaPublishError(f"{field}_required")
    if len(value) > maximum:
        raise MetaPublishError(f"{field}_too_long")
    return value


def _safe_identifier(value: Any, field: str) -> str:
    result = _text(value, field, required=True, maximum=200)
    if result is None or not re.fullmatch(r"[A-Za-z0-9_.:-]+", result):
        raise MetaPublishError(f"invalid_{field}")
    return result


def _public_https_url(value: Any, field: str) -> str:
    result = _text(value, field, required=True, maximum=4_000)
    if result is None:
        raise MetaPublishError(f"{field}_required")
    parsed = urlparse(result)
    hostname = parsed.hostname
    if parsed.scheme != "https" or not hostname or parsed.username or parsed.password or parsed.fragment:
        raise MetaPublishError(f"invalid_{field}")
    lowered = hostname.lower().rstrip(".")
    if lowered in {"localhost", "localhost.localdomain"}:
        raise MetaPublishError(f"invalid_{field}")
    try:
        address = ipaddress.ip_address(lowered)
    except ValueError:
        address = None
    if address is not None and (address.is_private or address.is_loopback or address.is_link_local or address.is_reserved):
        raise MetaPublishError(f"invalid_{field}")
    return result


def _scheduled_time(value: Any) -> int | str | None:
    if value is None:
        return None
    if isinstance(value, bool):
        raise MetaPublishError("invalid_scheduled_publish_time")
    if isinstance(value, int):
        now = int(time.time())
        if value < now + 600 or value > now + 30 * 24 * 60 * 60:
            raise MetaPublishError("scheduled_publish_time_out_of_range")
        return value
    if isinstance(value, str) and value.strip():
        # Meta also accepts parseable ISO/strtotime values.  Keep the value
        # opaque after rejecting control characters; Meta remains authoritative
        # for provider-side date parsing.
        result = value.strip()
        if len(result) > 100 or any(ord(char) < 32 for char in result):
            raise MetaPublishError("invalid_scheduled_publish_time")
        return result
    raise MetaPublishError("invalid_scheduled_publish_time")


def normalize_publish_request(args: dict[str, Any]) -> PublishPlan:
    if not isinstance(args, dict):
        raise MetaPublishError("invalid_publish_arguments")
    channel = str(args.get("channel", "")).strip().lower()
    if channel in {"facebook", "facebook_page", "page"}:
        channel = "facebook_page"
    elif channel in {"instagram", "instagram_professional"}:
        channel = "instagram"
    else:
        raise MetaPublishError("unsupported_publish_channel")
    account_id = _safe_identifier(args.get("account_id"), "account_id")
    media_type = str(args.get("media_type", "")).strip().lower()
    if media_type not in {"text", "link", "image", "video", "reel"}:
        raise MetaPublishError("unsupported_media_type")
    caption = _text(args.get("caption", ""), "caption", maximum=10_000) or ""
    media_url = args.get("media_url")
    link = args.get("link")
    alt_text = _text(args.get("alt_text"), "alt_text", maximum=1_000)
    is_ai_generated = args.get("is_ai_generated", False)
    if not isinstance(is_ai_generated, bool):
        raise MetaPublishError("invalid_is_ai_generated")
    scheduled = _scheduled_time(args.get("scheduled_publish_time"))

    if channel == "instagram":
        if media_type not in {"image", "video", "reel"}:
            raise MetaPublishError("instagram_media_type_required")
        if scheduled is not None:
            raise MetaPublishError("instagram_scheduling_not_supported_by_adapter")
        media_url = _public_https_url(media_url, "media_url")
        if link is not None:
            raise MetaPublishError("instagram_link_not_supported_by_adapter")
    else:
        if media_type in {"image", "video", "reel"}:
            if media_type in {"video", "reel"}:
                raise MetaPublishError("facebook_video_requires_resumable_upload")
            media_url = _public_https_url(media_url, "media_url")
        elif media_type == "link":
            link = _public_https_url(link, "link")
        elif media_type == "text" and media_url is not None:
            raise MetaPublishError("text_media_url_not_supported")
        if link is not None and media_type != "link":
            raise MetaPublishError("link_only_supported_for_link_posts")

    return PublishPlan(
        channel=channel,
        account_id=account_id,
        media_type=media_type,
        caption=caption,
        media_url=media_url,
        link=link,
        alt_text=alt_text,
        is_ai_generated=is_ai_generated,
        scheduled_publish_time=scheduled,
    )


class MetaPublishClient:
    """Graph API client whose token boundary is the Meta OAuth client/vault."""

    def __init__(
        self,
        oauth: MetaOAuthClient | None = None,
        vault: UserVault | None = None,
        opener: Callable[..., Any] | None = None,
        sleeper: Callable[[float], None] | None = None,
        poll_interval: float | None = None,
        max_poll_attempts: int = 5,
    ) -> None:
        self.oauth = oauth or MetaOAuthClient()
        self.vault = vault or self.oauth.vault
        self._opener = opener or urlopen
        self._sleeper = sleeper or time.sleep
        configured_interval = os.environ.get("META_PUBLISH_POLL_INTERVAL", "5").strip()
        try:
            self.poll_interval = max(0.0, float(configured_interval)) if poll_interval is None else max(0.0, poll_interval)
        except ValueError:
            self.poll_interval = 5.0 if poll_interval is None else max(0.0, poll_interval)
        self.max_poll_attempts = max(1, min(int(max_poll_attempts), 10))

    def capabilities(self) -> dict[str, Any]:
        return {
            "provider": "meta",
            "mode": "approval_gated",
            "supported": {
                "facebook_page": {
                    "media_types": ["text", "link", "image"],
                    "scheduled_posts": True,
                    "requires_page_access_token": True,
                },
                "instagram": {
                    "media_types": ["image", "video", "reel"],
                    "scheduled_posts": False,
                    "requires_public_https_media_url": True,
                    "requires_professional_account": True,
                },
            },
            "unsupported_until_implemented": [
                "facebook_video_local_resumable_upload",
                "instagram_local_resumable_upload",
                "instagram_carousel",
                "stories",
                "provider_scheduling_queue",
            ],
            "required_permissions": [
                "pages_show_list",
                "pages_manage_posts",
                "pages_read_engagement",
                "pages_manage_engagement",
                "instagram_basic",
                "instagram_content_publish",
                "publish_video",
            ],
            "writes_enabled": False,
            "approval_required": True,
            "secrets_in_response": False,
            "vendor_credits_required": False,
            "provider_limits_still_apply": True,
        }

    def _api_version(self) -> str:
        value = self.oauth.config.api_version
        if not re.fullmatch(r"v\d+\.\d+", value):
            raise MetaPublishError("meta_publish_invalid_api_version")
        return value

    def _token(self) -> str:
        try:
            return self.oauth.access_token_for_internal_use()
        except MetaOAuthError as exc:
            raise MetaPublishError(str(exc)) from exc

    def _call(
        self,
        method: str,
        path: str,
        token: str,
        *,
        params: dict[str, Any] | None = None,
        body: dict[str, Any] | None = None,
        host: str = "graph.facebook.com",
        side_effect_started: bool = False,
    ) -> dict[str, Any]:
        version = self._api_version()
        clean_path = "/".join(part for part in path.split("/") if part)
        url = f"https://{host}/{version}/{clean_path}"
        if method.upper() == "GET" and params:
            url += "?" + urlencode({key: value for key, value in params.items() if value is not None})
        data = None
        headers = {"Accept": "application/json", "Authorization": f"Bearer {token}"}
        if body is not None:
            data = json.dumps(body, separators=(",", ":")).encode("utf-8")
            headers["Content-Type"] = "application/json"
        request = Request(url, data=data, headers=headers, method=method.upper())
        try:
            with self._opener(request, timeout=30) as response:
                raw = response.read(4_194_304)
        except HTTPError as exc:
            try:
                exc.read(1_048_576)
            except OSError:
                pass
            raise MetaPublishError("meta_provider_http_error", side_effect_started=side_effect_started) from exc
        except (URLError, TimeoutError, OSError) as exc:
            raise MetaPublishError("meta_provider_network_error", side_effect_started=side_effect_started) from exc
        try:
            value = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise MetaPublishError("meta_provider_invalid_response", side_effect_started=side_effect_started) from exc
        if not isinstance(value, dict):
            raise MetaPublishError("meta_provider_invalid_response", side_effect_started=side_effect_started)
        if isinstance(value.get("error"), dict):
            raise MetaPublishError("meta_provider_rejected_request", side_effect_started=side_effect_started)
        return value

    def discover_accounts(self) -> dict[str, Any]:
        """Discover Pages and connected Instagram professional accounts.

        Page access tokens are written only to the encrypted vault.  The
        returned records contain IDs, names and capability booleans only.
        """
        user_token = self._token()
        response = self._call(
            "GET",
            "/me/accounts",
            user_token,
            params={"fields": "id,name,tasks,access_token,instagram_business_account{id,username}", "limit": 100},
        )
        raw_accounts = response.get("data", [])
        if not isinstance(raw_accounts, list):
            raise MetaPublishError("meta_provider_invalid_accounts_response")
        records: list[dict[str, Any]] = []
        for item in raw_accounts:
            if not isinstance(item, dict):
                continue
            page_id = item.get("id")
            if not isinstance(page_id, str) or not page_id:
                continue
            page_token = item.get("access_token")
            token_available = isinstance(page_token, str) and bool(page_token)
            if token_available:
                try:
                    self.vault.set(f"meta.page.{page_id}", page_token)
                except VaultError as exc:
                    raise MetaPublishError("meta_account_token_storage_failed") from exc
            instagram = item.get("instagram_business_account")
            instagram_record = None
            if isinstance(instagram, dict) and isinstance(instagram.get("id"), str):
                instagram_record = {
                    "id": instagram["id"],
                    "username": instagram.get("username") if isinstance(instagram.get("username"), str) else None,
                }
            tasks = item.get("tasks")
            safe_tasks = sorted({task for task in tasks if isinstance(task, str)}) if isinstance(tasks, list) else []
            records.append(
                {
                    "page_id": page_id,
                    "name": item.get("name") if isinstance(item.get("name"), str) else None,
                    "tasks": safe_tasks,
                    "instagram": instagram_record,
                    "page_access_token_available": token_available,
                    "facebook_publish_ready": token_available and "CREATE_CONTENT" in safe_tasks,
                    "instagram_publish_ready": token_available and instagram_record is not None and "CREATE_CONTENT" in safe_tasks,
                }
            )
        try:
            self.vault.set("meta.accounts", json.dumps(records, separators=(",", ":")))
        except VaultError as exc:
            raise MetaPublishError("meta_account_metadata_storage_failed") from exc
        return {"provider": "meta", "accounts": records, "count": len(records), "synced": True, "secrets_in_response": False}

    def stored_accounts(self) -> dict[str, Any]:
        try:
            raw = self.vault.get("meta.accounts")
        except VaultError as exc:
            raise MetaPublishError("meta_account_metadata_unreadable") from exc
        if not raw:
            return {"provider": "meta", "accounts": [], "count": 0, "discovered": False, "secrets_in_response": False}
        try:
            records = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise MetaPublishError("meta_account_metadata_invalid") from exc
        if not isinstance(records, list):
            raise MetaPublishError("meta_account_metadata_invalid")
        sanitized = [item for item in records if isinstance(item, dict)]
        for item in sanitized:
            page_id = item.get("page_id")
            if isinstance(page_id, str):
                try:
                    item["page_access_token_available"] = bool(self.vault.get(f"meta.page.{page_id}"))
                except VaultError as exc:
                    raise MetaPublishError("meta_account_token_unreadable") from exc
        return {"provider": "meta", "accounts": sanitized, "count": len(sanitized), "discovered": True, "secrets_in_response": False}

    def _account(self, plan: PublishPlan) -> tuple[dict[str, Any], str]:
        stored = self.stored_accounts()["accounts"]
        for item in stored:
            page_id = item.get("page_id")
            if plan.channel == "facebook_page" and page_id == plan.account_id:
                target = item
            elif plan.channel == "instagram" and isinstance(item.get("instagram"), dict) and item["instagram"].get("id") == plan.account_id:
                target = item
            else:
                continue
            if not isinstance(page_id, str):
                break
            try:
                token = self.vault.get(f"meta.page.{page_id}")
            except VaultError as exc:
                raise MetaPublishError("meta_account_token_unreadable") from exc
            if not token:
                raise MetaPublishError("meta_page_access_token_not_available")
            return target, token
        raise MetaPublishError("meta_account_not_discovered")

    def publish(self, plan: PublishPlan) -> dict[str, Any]:
        # Fail with the connection state before account lookup.  This keeps a
        # first-run setup error actionable and guarantees no provider request
        # can occur when OAuth has not completed.
        self._token()
        account, page_token = self._account(plan)
        if plan.channel == "facebook_page":
            return self._publish_facebook(plan, account, page_token)
        return self._publish_instagram(plan, account, page_token)

    def _publish_facebook(self, plan: PublishPlan, account: dict[str, Any], token: str) -> dict[str, Any]:
        page_id = str(account["page_id"])
        if plan.media_type in {"text", "link"}:
            body: dict[str, Any] = {"published": plan.scheduled_publish_time is None}
            if plan.caption:
                body["message"] = plan.caption
            if plan.link:
                body["link"] = plan.link
            if plan.scheduled_publish_time is not None:
                body["scheduled_publish_time"] = plan.scheduled_publish_time
            response = self._call("POST", f"/{page_id}/feed", token, body=body, side_effect_started=True)
            return {"provider": "meta", "channel": "facebook_page", "account_id": page_id, "status": "published", "post_id": response.get("id"), "provider_response": {"id": response.get("id")}}
        if plan.media_type == "image" and plan.media_url:
            body = {"url": plan.media_url, "published": True}
            if plan.caption:
                body["message"] = plan.caption
            response = self._call("POST", f"/{page_id}/photos", token, body=body, side_effect_started=True)
            return {"provider": "meta", "channel": "facebook_page", "account_id": page_id, "status": "published", "post_id": response.get("post_id") or response.get("id"), "photo_id": response.get("id")}
        raise MetaPublishError("unsupported_facebook_publish_plan")

    def _publish_instagram(self, plan: PublishPlan, account: dict[str, Any], token: str) -> dict[str, Any]:
        instagram = account.get("instagram")
        if not isinstance(instagram, dict) or not isinstance(instagram.get("id"), str):
            raise MetaPublishError("instagram_account_not_available")
        instagram_id = instagram["id"]
        body: dict[str, Any] = {"is_ai_generated": plan.is_ai_generated}
        if plan.caption:
            body["caption"] = plan.caption
        if plan.alt_text:
            body["alt_text"] = plan.alt_text
        if plan.media_type == "image" and plan.media_url:
            body["image_url"] = plan.media_url
        elif plan.media_type in {"video", "reel"} and plan.media_url:
            body["video_url"] = plan.media_url
            body["media_type"] = "REELS" if plan.media_type == "reel" else "VIDEO"
        else:
            raise MetaPublishError("unsupported_instagram_publish_plan")
        container = self._call("POST", f"/{instagram_id}/media", token, body=body, side_effect_started=True)
        container_id = container.get("id")
        if not isinstance(container_id, str) or not container_id:
            raise MetaPublishError("meta_provider_missing_container_id", side_effect_started=True)
        if plan.media_type in {"video", "reel"}:
            self._wait_for_container(container_id, token)
        published = self._call(
            "POST",
            f"/{instagram_id}/media_publish",
            token,
            body={"creation_id": container_id},
            side_effect_started=True,
        )
        return {
            "provider": "meta",
            "channel": "instagram",
            "account_id": instagram_id,
            "status": "published",
            "container_id": container_id,
            "media_id": published.get("id"),
        }

    def _wait_for_container(self, container_id: str, token: str) -> None:
        last_status = None
        for attempt in range(self.max_poll_attempts):
            response = self._call("GET", f"/{container_id}", token, params={"fields": "status_code"})
            last_status = response.get("status_code")
            if last_status in {"FINISHED", "PUBLISHED"}:
                return
            if last_status in {"ERROR", "EXPIRED"}:
                raise MetaPublishError(f"instagram_container_{str(last_status).lower()}", side_effect_started=True)
            if attempt + 1 < self.max_poll_attempts and self.poll_interval:
                self._sleeper(self.poll_interval)
        raise MetaPublishError("instagram_container_not_ready", side_effect_started=True)

