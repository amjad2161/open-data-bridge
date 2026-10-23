"""One-time loopback bootstrap for the OpenAI tunnel runtime.

This helper exists only to bridge a browser-isolated clipboard into a child
process environment. It binds to loopback, accepts one POST, never logs the
credential, starts tunnel-client with the credential in its process
environment, and shuts down its own HTTP listener.
"""

from __future__ import annotations

import html
import os
import re
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs


ROOT = Path(__file__).resolve().parent
TUNNEL_CLIENT = ROOT / ".artifacts" / "tunnel-client" / "tunnel-client.exe"
TUNNEL_ID = "tunnel_6adb4f3017ac8191a5e8ca861886d5df"
MCP_URL = "http://127.0.0.1:8788/mcp"
HEALTH_ADDR = "127.0.0.1:8080"
RUNTIME_LOG = ROOT / ".artifacts" / "tunnel-client" / "runtime.log"
MAX_BODY = 4096
KEY_PATTERN = re.compile(r"^sk-[A-Za-z0-9_-]{20,}$")


class BootstrapHandler(BaseHTTPRequestHandler):
    server_version = "OpenDataBridgeBootstrap/1.0"

    def log_message(self, *_args: object) -> None:
        return

    def _send_html(self, status: int, body: str) -> None:
        payload = body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(payload)

    def _send_json(self, status: int, payload: str) -> None:
        body = payload.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802
        if self.path == "/":
            self._send_html(
                200,
                """<!doctype html><meta charset=utf-8><title>Open Data Bridge bootstrap</title>
                <h1>Open Data Bridge tunnel bootstrap</h1>
                <p>This loopback page accepts one runtime key and closes after starting tunnel-client.</p>
                <form method=post action=/start>
                  <label>Runtime key <input name=key type=password autocomplete=off required></label>
                  <button type=submit>Start tunnel</button>
                </form>""",
            )
            return
        self._send_json(404, '{"error":"not_found"}')

    def do_POST(self) -> None:  # noqa: N802
        if self.path != "/start":
            self._send_json(404, '{"error":"not_found"}')
            return
        if not TUNNEL_CLIENT.is_file():
            self._send_json(500, '{"error":"tunnel_client_missing"}')
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            length = -1
        if length < 0 or length > MAX_BODY:
            self._send_json(413, '{"error":"request_too_large"}')
            return
        values = parse_qs(self.rfile.read(length).decode("utf-8"), strict_parsing=False)
        key = values.get("key", [""])[0].strip()
        if not KEY_PATTERN.fullmatch(key):
            self._send_json(400, '{"error":"invalid_runtime_key"}')
            return

        env = os.environ.copy()
        env["CONTROL_PLANE_API_KEY"] = key
        env["CONTROL_PLANE_TUNNEL_ID"] = TUNNEL_ID
        env["MCP_SERVER_URL"] = MCP_URL
        RUNTIME_LOG.parent.mkdir(parents=True, exist_ok=True)
        command = [
            str(TUNNEL_CLIENT),
            "run",
            "--control-plane.api-key",
            "env:CONTROL_PLANE_API_KEY",
            "--control-plane.tunnel-id",
            TUNNEL_ID,
            "--mcp.server-url",
            f"url={MCP_URL}",
            "--health.listen-addr",
            HEALTH_ADDR,
            "--log.file",
            str(RUNTIME_LOG),
            "--log.format",
            "struct-text",
        ]
        creation_flags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0) | getattr(subprocess, "DETACHED_PROCESS", 0)
        try:
            process = subprocess.Popen(
                command,
                cwd=ROOT,
                env=env,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=creation_flags,
            )
        except OSError:
            self._send_json(500, '{"error":"tunnel_client_start_failed"}')
            return

        self._send_json(200, f'{{"started":true,"pid":{process.pid}}}')
        threading.Thread(target=self.server.shutdown, daemon=True).start()


def main() -> None:
    server = ThreadingHTTPServer(("127.0.0.1", 8799), BootstrapHandler)
    print("Open Data Bridge bootstrap listening on http://127.0.0.1:8799", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()

