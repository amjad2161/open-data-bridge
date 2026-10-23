import unittest

from bridge_catalog import ContractError, capability_matrix, get_custom_fields, get_options, list_connectors, query_data, to_csv


class BridgeCatalogTests(unittest.TestCase):
    def test_full_catalog_marks_unimplemented_connectors_explicitly(self):
        items = list_connectors(include_not_yet_connected=True)
        ids = {item["id"] for item in items}
        self.assertIn("all", ids)
        self.assertIn("meta_ads", ids)
        meta = next(item for item in items if item["id"] == "meta_ads")
        self.assertEqual(meta["implementation_status"], "catalog_only")
        self.assertFalse(meta["available"])

    def test_blended_query_supports_breakdown_filters_and_pagination(self):
        result = query_data(
            "all",
            ["source", "spend", "conversions", "roas"],
            {"group_by": ["source"], "filters": {"source": {"operator": "contains", "value": "ads"}}, "page_size": 1},
        )
        self.assertEqual(result["count"], 1)
        self.assertEqual(result["total_count"], 3)
        self.assertEqual(result["rows"][0]["source"], "meta_ads")
        self.assertIsNotNone(result["next_cursor"])

    def test_cursor_and_csv_export_are_deterministic(self):
        first = query_data("demo_ads", ["date", "campaign", "spend"], {"page_size": 2})
        second = query_data("demo_ads", ["date", "campaign", "spend"], {"page_size": 2, "cursor": first["next_cursor"]})
        self.assertEqual(first["count"], 2)
        self.assertEqual(second["count"], 1)
        self.assertIsNone(second["next_cursor"])
        self.assertIn("campaign,spend", to_csv(first))

    def test_options_and_custom_fields_are_exposed(self):
        options = get_options("all")
        self.assertIn("last_30_days", options["date_presets"])
        self.assertIn("source", options["breakdowns"])
        custom = get_custom_fields("all")
        self.assertIn("roas", {item["id"] for item in custom["custom_fields"]})

    def test_unavailable_provider_is_fail_closed(self):
        with self.assertRaises(ContractError):
            query_data("meta_ads", ["date", "spend"])
        matrix = capability_matrix()
        self.assertFalse(matrix["writes_enabled"])
        self.assertFalse(matrix["unlimited_claim"])


if __name__ == "__main__":
    unittest.main()

