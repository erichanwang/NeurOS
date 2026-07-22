#!/usr/bin/env python3
"""
test_mcp.py — Unit tests for neuros-mcp (the MCP server).
Tests tool handlers directly without starting an HTTP server or requiring Ollama.
"""

import os
import http.client
import json
import threading
import tempfile
import unittest
import importlib.util
from importlib.machinery import SourceFileLoader

MCP_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..",
    "config", "includes.chroot", "usr", "local", "bin", "neuros-mcp"
)


def load_neuros_mcp():
    loader = SourceFileLoader("neuros_mcp", MCP_PATH)
    spec = importlib.util.spec_from_loader("neuros_mcp", loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


class TestMCPTools(unittest.TestCase):
    def setUp(self):
        self.mcp = load_neuros_mcp()
        # Build a handler instance without running BaseHTTPRequestHandler.__init__
        # (which would try to read from a real socket).
        self.handler = self.mcp.MCPServer.__new__(self.mcp.MCPServer)

    def test_list_tools_declares_expected_tools(self):
        result = self.handler.handle_list_tools()
        names = {t["name"] for t in result["tools"]}
        self.assertEqual(
            names,
            {"read_file", "list_directory", "run_command", "ask_llm",
             "get_system_info", "git_status"}
        )

    def test_read_file_returns_content(self):
        with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False) as f:
            f.write("hello mcp")
            path = f.name
        try:
            result = self.handler.tool_read_file({"path": path})
            self.assertEqual(result["content"][0]["text"], "hello mcp")
        finally:
            os.unlink(path)

    def test_read_file_missing_reports_error(self):
        result = self.handler.tool_read_file({"path": "/nonexistent/path/xyz"})
        self.assertTrue(result.get("isError"))

    def test_run_command_blocks_shell_metacharacters(self):
        # shlex.split treats "&&" as a literal argument, not a shell operator,
        # so "echo hi && ls" runs `echo` with literal args -- no injection.
        result = self.handler.tool_run_command({"command": "echo hi && ls"})
        self.assertEqual(result["content"][0]["text"].strip(), "hi && ls")

    def test_run_command_missing_binary(self):
        result = self.handler.tool_run_command({"command": "this-binary-does-not-exist-xyz"})
        self.assertTrue(result.get("isError"))

    def test_call_tool_unknown_name(self):
        result = self.handler.handle_call_tool({"name": "no_such_tool", "arguments": {}})
        value, error = result
        self.assertIsNone(value)
        self.assertEqual(error["code"], -32602)


class TestMCPWireProtocol(unittest.TestCase):
    def setUp(self):
        self.mcp = load_neuros_mcp()
        self.server = self.mcp.HTTPServer(("127.0.0.1", 0), self.mcp.MCPServer)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.host, self.port = self.server.server_address

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)

    def post(self, message, *, accept="application/json, text/event-stream",
             content_type="application/json"):
        body = json.dumps(message).encode("utf-8") if not isinstance(message, bytes) else message
        connection = http.client.HTTPConnection(self.host, self.port, timeout=2)
        connection.request("POST", "/", body=body,
                           headers={"Accept": accept, "Content-Type": content_type})
        response = connection.getresponse()
        raw_body = response.read()
        connection.close()
        return response, raw_body

    def test_initialize_handshake_and_capabilities_are_wire_valid(self):
        response, body = self.post({
            "jsonrpc": "2.0",
            "id": 7,
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {"roots": {"listChanged": True}},
                "clientInfo": {"name": "wire-test", "version": "1.0"},
            },
        })
        message = json.loads(body)
        self.assertEqual(response.status, 200)
        self.assertEqual(response.getheader("Content-Type"), "application/json")
        self.assertEqual(int(response.getheader("Content-Length")), len(body))
        self.assertEqual(message["jsonrpc"], "2.0")
        self.assertEqual(message["id"], 7)
        self.assertEqual(message["result"]["protocolVersion"], "2024-11-05")
        self.assertEqual(message["result"]["capabilities"], {"tools": {}, "resources": {}})
        self.assertEqual(set(message["result"]["serverInfo"]), {"name", "version"})

    def test_initialize_rejects_unsupported_version_with_invalid_params(self):
        response, body = self.post({
            "jsonrpc": "2.0", "id": "version", "method": "initialize",
            "params": {
                "protocolVersion": "2099-01-01", "capabilities": {},
                "clientInfo": {"name": "wire-test", "version": "1.0"},
            },
        })
        message = json.loads(body)
        self.assertEqual(response.status, 200)
        self.assertEqual(message["error"]["code"], -32602)
        self.assertEqual(message["error"]["data"], {
            "supported": ["2024-11-05"], "requested": "2099-01-01"})

    def test_json_rpc_error_code_mapping_is_wire_valid(self):
        cases = [
            (b"not-json", -32700, 400),
            ({"jsonrpc": "2.0", "id": 1}, -32600, 400),
            ({"jsonrpc": "2.0", "id": {"bad": "id"}, "method": "tools/list"}, -32600, 400),
            ({"jsonrpc": "2.0", "id": 2, "method": "no/such"}, -32601, 200),
            ({"jsonrpc": "2.0", "id": 3, "method": "tools/call",
              "params": {"name": "no_such_tool", "arguments": {}}}, -32602, 200),
        ]
        for message, expected_code, expected_status in cases:
            with self.subTest(expected_code=expected_code):
                response, body = self.post(message)
                payload = json.loads(body)
                self.assertEqual(response.status, expected_status)
                self.assertEqual(payload["jsonrpc"], "2.0")
                self.assertEqual(payload["error"]["code"], expected_code)
                if expected_code == -32600:
                    self.assertIsNone(payload["id"])

    def test_notification_returns_202_without_json_rpc_body(self):
        response, body = self.post({"jsonrpc": "2.0", "method": "notifications/initialized"})
        self.assertEqual(response.status, 202)
        self.assertEqual(body, b"")
        self.assertEqual(response.getheader("Content-Length"), "0")

    def test_streamable_http_accept_header_is_required(self):
        response, body = self.post({"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
                                   accept="application/json")
        message = json.loads(body)
        self.assertEqual(response.status, 400)
        self.assertEqual(message["error"]["code"], -32600)

    def test_json_content_type_must_be_exact_media_type(self):
        response, body = self.post({"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
                                   content_type="application/jsonp")
        message = json.loads(body)
        self.assertEqual(response.status, 400)
        self.assertEqual(message["error"]["code"], -32600)


if __name__ == "__main__":
    unittest.main()
