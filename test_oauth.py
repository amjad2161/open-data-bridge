import unittest

from oauth import OAuthStateStore, authorization_url, pkce_challenge


class OAuthTests(unittest.TestCase):
    def test_pkce_is_deterministic_and_url_safe(self):
        challenge = pkce_challenge("verifier")
        self.assertEqual(challenge, pkce_challenge("verifier"))
        self.assertNotIn("=", challenge)

    def test_state_is_one_time_and_connector_bound(self):
        store = OAuthStateStore()
        item = store.create("googleanalytics4", now=100.0)
        consumed = store.consume(item.state, now=101.0)
        self.assertEqual(consumed.connector_id, "googleanalytics4")
        with self.assertRaises(ValueError):
            store.consume(item.state, now=102.0)

    def test_expired_state_fails_closed(self):
        store = OAuthStateStore()
        item = store.create("google_ads", now=100.0)
        with self.assertRaises(ValueError):
            store.consume(item.state, now=701.0)

    def test_authorization_url_has_pkce_and_state(self):
        store = OAuthStateStore()
        item = store.create("demo", now=100.0)
        url = authorization_url("https://provider.example/authorize", "client", "http://127.0.0.1/callback", item, ["read"])
        self.assertIn("code_challenge_method=S256", url)
        self.assertIn("state=", url)


if __name__ == "__main__":
    unittest.main()

