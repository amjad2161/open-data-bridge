import unittest

from connectors import Account, ConnectorRegistry, Field, OfficialApiPolicy


class FakeConnector:
    connector_id = "fake"

    def fields(self, account):
        return [Field("value", "NUMERIC", "metric")]

    def query(self, account, fields, options):
        return [{"value": 1}]


class ConnectorContractTests(unittest.TestCase):
    def test_registry_is_deterministic_and_rejects_duplicates(self):
        registry = ConnectorRegistry()
        registry.register(FakeConnector())
        self.assertEqual(registry.ids(), ["fake"])
        with self.assertRaises(ValueError):
            registry.register(FakeConnector())

    def test_policy_retries_provider_transient_failures_only(self):
        policy = OfficialApiPolicy()
        self.assertTrue(policy.retryable_status(429))
        self.assertTrue(policy.retryable_status(503))
        self.assertFalse(policy.retryable_status(400))

    def test_account_and_field_contracts(self):
        account = Account("a1", "Demo", "demo")
        field = FakeConnector().fields(account)[0]
        self.assertEqual(field.role, "metric")
        self.assertEqual(account.provider, "demo")


if __name__ == "__main__":
    unittest.main()

