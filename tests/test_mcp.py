#!/usr/bin/env python3
"""
test_mcp.py — Unit tests for neuros-mcp (the MCP server).
Tests tool handlers directly without starting an HTTP server or requiring Ollama.
"""

import os
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
        self.assertIn("error", result)


class TestDispatchRequest(unittest.TestCase):
    """dispatch_request is the shared router behind both the HTTP transport
    (do_POST) and the stdio transport (run_stdio) -- exercise it directly
    against real MCP JSON-RPC shapes, since that's what a real client sends."""

    def setUp(self):
        self.mcp = load_neuros_mcp()
        self.handler = self.mcp.MCPServer.__new__(self.mcp.MCPServer)

    def test_initialize_returns_protocol_version_and_id(self):
        response = self.mcp.dispatch_request(self.handler, {
            "jsonrpc": "2.0", "id": 1, "method": "initialize",
            "params": {"protocolVersion": "2024-11-05", "capabilities": {},
                       "clientInfo": {"name": "test-client", "version": "0.1"}}
        })
        self.assertEqual(response["id"], 1)
        self.assertEqual(response["result"]["protocolVersion"], "2024-11-05")

    def test_notification_gets_no_response(self):
        # Per the MCP spec, requests without an "id" are notifications and
        # must not receive a reply.
        response = self.mcp.dispatch_request(
            self.handler, {"jsonrpc": "2.0", "method": "notifications/initialized"}
        )
        self.assertIsNone(response)

    def test_unknown_method_returns_json_rpc_error(self):
        response = self.mcp.dispatch_request(
            self.handler, {"jsonrpc": "2.0", "id": 5, "method": "no/such/method"}
        )
        self.assertEqual(response["error"]["code"], -32601)
        self.assertEqual(response["id"], 5)


if __name__ == "__main__":
    unittest.main()
