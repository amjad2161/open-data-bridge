import json
import time
import unittest
from urllib.parse import urlparse

from meta_oauth import MetaOAuthClient, MetaOAuthConfig
from meta_publish import MetaPublishClient, MetaPublishError, normalize_publish_request


class FakeVault:
    def __init__(self):
        self.values = {}

    def set(self, key, value):
        self.values[key] = value

    def get(self, key):
        return self.values.get(key)

    def delete(self, key):
        self.values.pop(key, None)


class FakeResponse:
    def __init__(self, payload):
        self.payload = json.dumps(payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self, _limit):
        return self.payload


def connected_oauth(vault):
    vault.set("meta.oauth", json.dumps({"access_token": "user-secret", "stored_at": 4_000_000_000}))
    return MetaOAuthClient(
        config=MetaOAuthConfig(
            app_id="123",
            app_secret="not-used-by-publish",
            api_version="v26.0",
            redirect_uri="https://bridge.example/oauth/meta/callback",
            scopes=("pages_show_list", "pages_manage_posts", "instagram_content_publish"),
        ),
        vault=vault,
    )


class MetaPublishTests(unittest.TestCase):
    def test_public_media_urls_are_required_and_private_urls_rejected(self):
        with self.assertRaisesRegex(MetaPublishError, "invalid_media_url"):
            normalize_publish_request({
                "channel": "instagram",
                "account_id": "1789",
                "media_type": "image",
                "media_url": "http://127.0.0.1/image.jpg",
            })
        plan = normalize_publish_request({
            "channel": "instagram",
            "account_id": "1789",
            "media_type": "image",
            "media_url": "https://cdn.example.test/image.jpg",
            "caption": "hello",
        })
        self.assertEqual(plan.channel, "instagram")
        self.assertEqual(plan.media_url, "https://cdn.example.test/image.jpg")

    def test_discovery_stores_page_token_but_returns_no_secret(self):
        vault = FakeVault()
        oauth = connected_oauth(vault)
        requests = []

        def opener(request, timeout):
            requests.append(request)
            return FakeResponse({
                "data": [{
                    "id": "page-1",
                    "name": "Example Page",
                    "tasks": ["CREATE_CONTENT", "MANAGE"],
                    "access_token": "page-secret",
                    "instagram_business_account": {"id": "ig-1", "username": "example"},
                }]
            })

        result = MetaPublishClient(oauth=oauth, vault=vault, opener=opener).discover_accounts()
        encoded = json.dumps(result)
        self.assertNotIn("page-secret", encoded)
        self.assertNotIn("user-secret", encoded)
        self.assertEqual(result["accounts"][0]["page_id"], "page-1")
        self.assertEqual(vault.get("meta.page.page-1"), "page-secret")
        self.assertNotIn("user-secret", requests[0].full_url)
        self.assertNotIn("page-secret", requests[0].full_url)
        self.assertEqual(requests[0].get_header("Authorization"), "Bearer user-secret")

    def test_instagram_image_publish_uses_container_then_publish(self):
        vault = FakeVault()
        oauth = connected_oauth(vault)
        vault.set("meta.page.page-1", "page-secret")
        vault.set("meta.accounts", json.dumps([{
            "page_id": "page-1",
            "name": "Example Page",
            "tasks": ["CREATE_CONTENT"],
            "instagram": {"id": "ig-1", "username": "example"},
        }]))
        requests = []
        responses = iter([{"id": "container-1"}, {"id": "media-1"}])

        def opener(request, timeout):
            requests.append(request)
            return FakeResponse(next(responses))

        plan = normalize_publish_request({
            "channel": "instagram",
            "account_id": "ig-1",
            "media_type": "image",
            "media_url": "https://cdn.example.test/image.jpg",
            "caption": "hello",
        })
        result = MetaPublishClient(oauth=oauth, vault=vault, opener=opener, poll_interval=0).publish(plan)
        self.assertEqual(result["media_id"], "media-1")
        self.assertEqual(len(requests), 2)
        self.assertTrue(all("page-secret" not in request.full_url for request in requests))
        self.assertTrue(all(request.get_header("Authorization") == "Bearer page-secret" for request in requests))
        self.assertIn("creation_id", requests[1].data.decode("utf-8"))

    def test_video_waits_for_finished_container_and_does_not_retry_publish(self):
        vault = FakeVault()
        oauth = connected_oauth(vault)
        vault.set("meta.page.page-1", "page-secret")
        vault.set("meta.accounts", json.dumps([{
            "page_id": "page-1",
            "tasks": ["CREATE_CONTENT"],
            "instagram": {"id": "ig-1"},
        }]))
        requests = []
        responses = iter([{"id": "container-1"}, {"status_code": "IN_PROGRESS"}, {"status_code": "FINISHED"}, {"id": "media-1"}])

        def opener(request, timeout):
            requests.append(request)
            return FakeResponse(next(responses))

        plan = normalize_publish_request({
            "channel": "instagram",
            "account_id": "ig-1",
            "media_type": "reel",
            "media_url": "https://cdn.example.test/reel.mp4",
        })
        result = MetaPublishClient(oauth=oauth, vault=vault, opener=opener, sleeper=lambda _seconds: None, poll_interval=0).publish(plan)
        self.assertEqual(result["media_id"], "media-1")
        self.assertEqual(len(requests), 4)
        self.assertIn("status_code", requests[1].full_url)
        self.assertIn("media_type", requests[0].data.decode("utf-8"))

    def test_facebook_text_scheduling_is_normalized(self):
        vault = FakeVault()
        oauth = connected_oauth(vault)
        vault.set("meta.page.page-1", "page-secret")
        vault.set("meta.accounts", json.dumps([{"page_id": "page-1", "tasks": ["CREATE_CONTENT"]}]))
        requests = []

        def opener(request, timeout):
            requests.append(request)
            return FakeResponse({"id": "page-post-1"})

        plan = normalize_publish_request({
            "channel": "facebook_page",
            "account_id": "page-1",
            "media_type": "text",
            "caption": "scheduled",
            "scheduled_publish_time": int(time.time()) + 900,
        })
        result = MetaPublishClient(oauth=oauth, vault=vault, opener=opener).publish(plan)
        self.assertEqual(result["post_id"], "page-post-1")
        body = requests[0].data.decode("utf-8")
        self.assertIn('"published":false', body)
        self.assertIn("scheduled_publish_time", body)

    def test_unconnected_oauth_never_calls_provider(self):
        vault = FakeVault()
        oauth = MetaOAuthClient(
            config=MetaOAuthConfig("123", "secret", "v26.0", "https://bridge.example/callback", ("pages_show_list",)),
            vault=vault,
        )
        calls = []

        def opener(request, timeout):
            calls.append(request)
            return FakeResponse({})

        client = MetaPublishClient(oauth=oauth, vault=vault, opener=opener)
        with self.assertRaisesRegex(MetaPublishError, "meta_oauth_not_connected"):
            client.discover_accounts()
        self.assertEqual(calls, [])


if __name__ == "__main__":
    unittest.main()

