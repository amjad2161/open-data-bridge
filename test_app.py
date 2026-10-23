import json
import os
import threading
import unittest
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer
from unittest.mock import patch

from app import Handler


class BridgeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.port = cls.server.server_port

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def get(self, path):
        conn = HTTPConnection("127.0.0.1", self.port)
        conn.request("GET", path)
        response = conn.getresponse()
        data = json.loads(response.read())
        conn.close()
        return response.status, data

    def post(self, path, payload):
        conn = HTTPConnection("127.0.0.1", self.port)
        body = json.dumps(payload)
        conn.request("POST", path, body=body, headers={"Content-Type": "application/json"})
        response = conn.getresponse()
        data = json.loads(response.read())
        conn.close()
        return response.status, data

    def test_health_is_local_read_only(self):
        status, data = self.get("/health")
        self.assertEqual(status, 200)
        self.assertFalse(data["writes_enabled"])

    def test_connector_and_fields(self):
        status, data = self.get("/api/connectors")
        self.assertEqual(status, 200)
        self.assertEqual(data["data"][0]["id"], "demo_ads")
        status, data = self.get("/api/fields?connector=demo_ads")
        self.assertEqual(status, 200)
        self.assertIn("spend", data["fields"])

    def test_data_query_and_date_filter(self):
        status, data = self.get("/api/data?connector=demo_ads&fields=date,campaign,spend&date_from=2026-01-02")
        self.assertEqual(status, 200)
        self.assertEqual(data["count"], 1)
        self.assertEqual(data["rows"][0]["campaign"], "Example A")

    def test_date_range_is_validated(self):
        status, data = self.get("/api/data?connector=demo_ads&fields=date&date_from=2026-01-03&date_to=2026-01-01")
        self.assertEqual(status, 400)
        self.assertEqual(data["error"], "invalid_date_range")

    def test_invalid_field_fails_closed(self):
        status, data = self.get("/api/data?connector=demo_ads&fields=secret")
        self.assertEqual(status, 400)
        self.assertEqual(data["error"], "invalid_fields")

    def test_mcp_initialize_and_tools(self):
        status, data = self.post("/mcp", {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-03-26"}})
        self.assertEqual(status, 200)
        self.assertEqual(data["result"]["serverInfo"]["name"], "open-data-bridge")
        status, data = self.post("/mcp", {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}})
        self.assertEqual(status, 200)
        expected = {
            "get_current_user",
            "get_capabilities",
            "get_connectors",
            "get_connector_connect_info",
            "get_connector_authorization_url",
            "get_options",
            "get_fields",
            "get_custom_fields",
            "get_data",
            "export_data",
            "get_destinations",
            "get_destination_tasks",
            "get_destination_setup_info",
            "create_destination_task",
            "get_accounts",
            "get_sync_status",
            "get_subscription_url",
            "get_windsor_login_url",
            "contact_windsor",
            "list_actions",
            "create_custom_field",
            "preview_action",
            "execute_action",
            "get_meta_connect_url",
            "get_meta_connection_status",
            "get_publish_capabilities",
            "get_meta_accounts",
            "sync_meta_accounts",
            "preview_publish",
            "approve_publish",
            "publish_media",
        }
        self.assertEqual({tool["name"] for tool in data["result"]["tools"]}, expected)
        tools = {tool["name"]: tool for tool in data["result"]["tools"]}
        self.assertTrue(tools["get_data"]["annotations"]["readOnlyHint"])
        self.assertFalse(tools["get_meta_connect_url"]["annotations"]["readOnlyHint"])

    def test_mcp_capability_and_blended_contract(self):
        status, data = self.post("/mcp", {"jsonrpc": "2.0", "id": 7, "method": "tools/call", "params": {"name": "get_capabilities", "arguments": {}}})
        self.assertEqual(status, 200)
        self.assertEqual(data["result"]["structuredContent"]["contract_version"], "0.4")
        status, data = self.post("/mcp", {"jsonrpc": "2.0", "id": 8, "method": "tools/call", "params": {"name": "get_data", "arguments": {"connector": "all", "fields": ["source", "spend"], "group_by": ["source"], "page_size": 1}}})
        self.assertEqual(status, 200)
        self.assertEqual(data["result"]["structuredContent"]["count"], 1)
        self.assertIsNotNone(data["result"]["structuredContent"]["next_cursor"])

    def test_action_preview_is_redacted_and_execution_is_blocked(self):
        status, data = self.post("/mcp", {"jsonrpc": "2.0", "id": 9, "method": "tools/call", "params": {"name": "preview_action", "arguments": {"action_type": "publish_social_post", "payload": {"access_token": "do-not-return", "caption": "draft"}}}})
        self.assertEqual(status, 200)
        preview = data["result"]["structuredContent"]
        self.assertEqual(preview["payload"]["access_token"], "[REDACTED]")
        status, data = self.post("/mcp", {"jsonrpc": "2.0", "id": 10, "method": "tools/call", "params": {"name": "execute_action", "arguments": {"preview_id": preview["preview_id"], "confirmation_token": "confirmed"}}})
        self.assertEqual(status, 200)
        self.assertTrue(data["result"]["isError"])
        self.assertFalse(data["result"]["structuredContent"]["executed"])

    def test_publish_requires_explicit_approval_and_blocks_without_meta_connection(self):
        status, data = self.post("/mcp", {"jsonrpc": "2.0", "id": 11, "method": "tools/call", "params": {"name": "preview_publish", "arguments": {"channel": "instagram", "account_id": "ig-1", "media_type": "image", "media_url": "https://cdn.example.test/image.jpg", "caption": "draft"}}})
        self.assertEqual(status, 200)
        preview = data["result"]["structuredContent"]
        self.assertTrue(preview["requires_explicit_approval"])
        status, data = self.post("/mcp", {"jsonrpc": "2.0", "id": 12, "method": "tools/call", "params": {"name": "approve_publish", "arguments": {"preview_id": preview["preview_id"], "approval_phrase": "PUBLISH_NOW"}}})
        self.assertEqual(status, 200)
        approval = data["result"]["structuredContent"]
        self.assertTrue(approval["approved"])
        status, data = self.post("/mcp", {"jsonrpc": "2.0", "id": 13, "method": "tools/call", "params": {"name": "publish_media", "arguments": {"preview_id": preview["preview_id"], "approval_token": approval["approval_token"]}}})
        self.assertEqual(status, 200)
        self.assertTrue(data["result"]["isError"])
        result = data["result"]["structuredContent"]
        self.assertEqual(result["status"], "blocked")
        self.assertFalse(result["provider_request_made"])
        self.assertEqual(result["reason"], "meta_oauth_not_connected")

    def test_http_publish_dry_run_returns_success_without_provider_request(self):
        status, preview = self.post("/api/publish/preview", {"channel": "facebook", "account_id": "page-1", "media_type": "text", "caption": "verification-only"})
        self.assertEqual(status, 200)
        status, approval = self.post("/api/publish/approve", {"preview_id": preview["preview_id"], "approval_phrase": "PUBLISH_NOW"})
        self.assertEqual(status, 200)
        status, dry_run = self.post("/api/publish/execute", {"preview_id": preview["preview_id"], "approval_token": approval["approval_token"], "dry_run": True})
        self.assertEqual(status, 200)
        self.assertEqual(dry_run["status"], "dry_run")
        self.assertFalse(dry_run["provider_request_made"])

    def test_expanded_contract_is_present_and_fail_closed(self):
        status, data = self.get("/api/connectors?include_not_yet_connected=true")
        self.assertEqual(status, 200)
        self.assertGreaterEqual(len(data["data"]), 367)
        status, data = self.get("/api/actions?connector=google_ads")
        self.assertEqual(status, 200)
        self.assertIn("create_campaign", {item["id"] for item in data["actions"]})
        self.assertFalse(data["writes_enabled"])
        status, data = self.get("/api/destinations/setup-info?destination=bigquery")
        self.assertEqual(status, 200)
        self.assertFalse(data["sensitive_fields_entered_in_form"] is False)
        status, data = self.get("/api/subscription-url")
        self.assertEqual(status, 200)
        self.assertFalse(data["billing_enabled"])

    def test_nested_filters_and_windsor_aliases(self):
        status, data = self.get("/api/data?connector=all&fields=source,spend&filter=%5B%5B%5B%22source%22,%22eq%22,%22meta_ads%22%5D,%22or%22,%5B%22source%22,%22eq%22,%22google_ads%22%5D%5D%5D&date_preset=all")
        self.assertEqual(status, 200)
        self.assertEqual(data["count"], 3)

    def test_mcp_data_call_is_read_only(self):
        status, data = self.post("/mcp", {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "get_data", "arguments": {"connector": "demo_ads", "fields": ["campaign", "spend"]}}})
        self.assertEqual(status, 200)
        self.assertEqual(data["result"]["structuredContent"]["count"], 3)

    def test_mcp_data_call_applies_date_filter(self):
        status, data = self.post("/mcp", {"jsonrpc": "2.0", "id": 4, "method": "tools/call", "params": {"name": "get_data", "arguments": {"connector": "demo_ads", "fields": ["campaign", "spend"], "date_from": "2026-01-02"}}})
        self.assertEqual(status, 200)
        self.assertEqual(data["result"]["structuredContent"]["count"], 1)

    def test_mcp_invalid_params_fail_as_jsonrpc_errors(self):
        status, data = self.post("/mcp", {"jsonrpc": "2.0", "id": 5, "method": "initialize", "params": []})
        self.assertEqual(status, 200)
        self.assertEqual(data["error"]["code"], -32602)
        status, data = self.post("/mcp", {"jsonrpc": "2.0", "id": 6, "method": "tools/call", "params": {"name": "get_data", "arguments": {"connector": "demo_ads", "fields": [1]}}})
        self.assertEqual(status, 200)
        self.assertEqual(data["error"]["code"], -32602)

    def test_meta_connect_url_fails_closed_without_configuration(self):
        with patch.dict(os.environ, {key: "" for key in ("META_APP_ID", "META_APP_SECRET", "META_API_VERSION", "META_REDIRECT_URI", "META_OAUTH_SCOPES")}, clear=False):
            status, data = self.get("/api/meta/connect-url")
        self.assertEqual(status, 503)
        self.assertEqual(data["error"], "meta_oauth_not_ready")


if __name__ == "__main__":
    unittest.main()

