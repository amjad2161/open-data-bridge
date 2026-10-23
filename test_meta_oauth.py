import json
import unittest
from urllib.parse import parse_qs, urlparse

from meta_oauth import MetaOAuthClient, MetaOAuthConfig, MetaOAuthError
from oauth import OAuthStateStore


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


class MetaOAuthTests(unittest.TestCase):
    def setUp(self):
        self.config = MetaOAuthConfig(
            app_id="123456",
            app_secret="do-not-log",
            api_version="v99.0",
            redirect_uri="https://bridge.example/oauth/meta/callback",
            scopes=("ads_read", "instagram_basic"),
        )
        self.vault = FakeVault()
        self.requests = []

        def opener(request, timeout):
            self.requests.append((request, timeout))
            return FakeResponse({"access_token": "synthetic-token", "token_type": "bearer", "expires_in": 3600})

        self.client = MetaOAuthClient(
            config=self.config,
            state_store=OAuthStateStore(),
            vault=self.vault,
            opener=opener,
        )

    def test_start_builds_meta_url_without_secret(self):
        _item, url = self.client.start()
        parsed = parse_qs(urlparse(url).query)
        self.assertEqual(parsed["client_id"], ["123456"])
        self.assertEqual(parsed["redirect_uri"], [self.config.redirect_uri])
        self.assertIn("ads_read", parsed["scope"][0])
        self.assertIn("code_challenge", parsed)
        self.assertNotIn(self.config.app_secret, url)

    def test_complete_stores_token_and_status_does_not_return_it(self):
        item, _url = self.client.start()
        result = self.client.complete(item.state, "synthetic-code")
        self.assertTrue(result["connected"])
        self.assertEqual(len(self.requests), 1)
        body = self.requests[0][0].data.decode("utf-8")
        self.assertIn("client_secret=do-not-log", body)
        status = self.client.status()
        self.assertTrue(status["connected"])
        self.assertNotIn("access_token", status)

    def test_state_is_one_time(self):
        item, _url = self.client.start()
        self.client.complete(item.state, "synthetic-code")
        with self.assertRaises(MetaOAuthError):
            self.client.complete(item.state, "synthetic-code")

    def test_missing_configuration_fails_closed(self):
        client = MetaOAuthClient(
            config=MetaOAuthConfig("", "", "", "", ()),
            state_store=OAuthStateStore(),
            vault=self.vault,
        )
        with self.assertRaisesRegex(MetaOAuthError, "not_configured"):
            client.start()

    def test_invalid_public_redirect_is_rejected(self):
        client = MetaOAuthClient(
            config=MetaOAuthConfig("123", "secret", "v99.0", "http://bridge.example/callback", ("ads_read",)),
            state_store=OAuthStateStore(),
            vault=self.vault,
        )
        with self.assertRaisesRegex(MetaOAuthError, "requires_https"):
            client.start()


if __name__ == "__main__":
    unittest.main()

