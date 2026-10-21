#!/usr/bin/env python3
"""
test_neuros_mcp.py — HTTP-level security tests for neuros-mcp: no CORS,
Host/Origin checks, bearer token, and the run_command allowlist.
Starts the real HTTPServer on an ephemeral port in a thread.
"""

import os
import json
import threading
import unittest
import http.client
import importlib.util
from importlib.machinery import SourceFileLoader

MCP_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..",
    "config", "includes.chroot", "usr", "local", "bin", "neuros-mcp"
)
TOKEN = "test-token-123"


def load_neuros_mcp():
    loader = SourceFileLoader("neuros_mcp", MCP_PATH)
    spec = importlib.util.spec_from_loader("neuros_mcp", loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


class TestMCPHTTPSecurity(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        mcp = load_neuros_mcp()
        cls.server = mcp.HTTPServer(("127.0.0.1", 0), mcp.MCPServer)
        cls.server.token = TOKEN
        cls.port = cls.server.server_port
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def request(self, method="POST", body=None, headers=None, host=None):
        hdrs = {"Host": host or f"127.0.0.1:{self.port}",
                "Authorization": f"Bearer {TOKEN}",
                "Content-Type": "application/json"}
        hdrs.update(headers or {})
        hdrs = {k: v for k, v in hdrs.items() if v is not None}
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        conn.putrequest(method, "/", skip_host=True)
        data = json.dumps(body).encode() if body is not None else b""
        for k, v in hdrs.items():
            conn.putheader(k, v)
        conn.putheader("Content-Length", str(len(data)))
        conn.endheaders(data)
        resp = conn.getresponse()
        payload = resp.read()
        conn.close()
        self.assertIsNone(resp.getheader("Access-Control-Allow-Origin"))
        return resp.status, payload

    def run_cmd(self, command):
        status, payload = self.request(body={
            "jsonrpc": "2.0", "id": 1, "method": "tools/call",
            "params": {"name": "run_command", "arguments": {"command": command}}})
        self.assertEqual(status, 200)
        return json.loads(payload)["result"]

    def test_options_preflight_denied(self):
        status, _ = self.request("OPTIONS", headers={
            "Origin": "https://evil.example",
            "Access-Control-Request-Method": "POST"})
        self.assertEqual(status, 403)

    def test_evil_origin_rejected(self):
        status, _ = self.request(body={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
                                 headers={"Origin": "https://evil.example"})
        self.assertEqual(status, 403)

    def test_bad_host_rejected(self):
        for host in ("evil.example", f"evil.example:{self.port}", "127.0.0.1:1"):
            status, _ = self.request("GET", host=host)
            self.assertEqual(status, 403, host)

    def test_localhost_host_accepted(self):
        status, _ = self.request("GET", host=f"localhost:{self.port}")
        self.assertEqual(status, 200)

    def test_missing_or_wrong_token_401(self):
        for auth in (None, "Bearer wrong", TOKEN, f"Basic {TOKEN}"):
            status, _ = self.request(body={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
                                     headers={"Authorization": auth})
            self.assertEqual(status, 401, auth)

    def test_allowed_command_runs(self):
        result = self.run_cmd("pwd")
        self.assertFalse(result.get("isError"))
        self.assertEqual(result["content"][0]["text"].strip(), os.getcwd())

    def test_disallowed_commands_rejected(self):
        for cmd in ("bash -c id", "/bin/sh", "sh -c id", "python3 -c 'print(1)'",
                    "git push", "git -c core.pager=id log", "git branch -D main",
                    "git log --output=/tmp/x", "/usr/bin/ls", "env ls"):
            result = self.run_cmd(cmd)
            self.assertTrue(result.get("isError"), cmd)
            self.assertIn("not allowed", result["content"][0]["text"], cmd)


if __name__ == "__main__":
    unittest.main()
