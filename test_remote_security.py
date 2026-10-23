import os
import threading
import unittest
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer
from unittest.mock import patch

from app import Handler


class RemoteSecurityTests(unittest.TestCase):
    def request(self, port, path, headers=None):
        connection = HTTPConnection("127.0.0.1", port)
        connection.request("GET", path, headers=headers or {})
        response = connection.getresponse()
        body = response.read()
        connection.close()
        return response.status, body

    def test_non_loopback_bind_requires_bearer_secret(self):
        with patch.dict(os.environ, {"OPEN_DATA_BRIDGE_SHARED_SECRET": "test-secret"}, clear=False):
            server = ThreadingHTTPServer(("0.0.0.0", 0), Handler)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                status, _body = self.request(server.server_port, "/api/connectors")
                self.assertEqual(status, 401)
                status, _body = self.request(server.server_port, "/api/connectors", {"Authorization": "Bearer test-secret"})
                self.assertEqual(status, 200)
            finally:
                server.shutdown()
                server.server_close()

    def test_non_loopback_bind_without_secret_is_unavailable(self):
        with patch.dict(os.environ, {"OPEN_DATA_BRIDGE_SHARED_SECRET": ""}, clear=False):
            server = ThreadingHTTPServer(("0.0.0.0", 0), Handler)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                status, _body = self.request(server.server_port, "/api/connectors")
                self.assertEqual(status, 503)
            finally:
                server.shutdown()
                server.server_close()


if __name__ == "__main__":
    unittest.main()

