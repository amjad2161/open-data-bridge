import os
import tempfile
import unittest

from vault import UserVault, VaultError


@unittest.skipUnless(os.name == "nt", "DPAPI vault is Windows-only")
class VaultTests(unittest.TestCase):
    def test_round_trip_and_delete(self):
        with tempfile.TemporaryDirectory() as directory:
            vault = UserVault(os.path.join(directory, "vault.json"))
            vault.set("provider.refresh_token", "synthetic-secret")
            self.assertEqual(vault.get("provider.refresh_token"), "synthetic-secret")
            vault.delete("provider.refresh_token")
            self.assertIsNone(vault.get("provider.refresh_token"))

    def test_corrupt_vault_fails_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "vault.json")
            with open(path, "w", encoding="utf-8") as handle:
                handle.write("not-json")
            with self.assertRaises(VaultError):
                UserVault(path).get("token")


if __name__ == "__main__":
    unittest.main()

