from __future__ import annotations

import asyncio
import json
import sys
import tempfile
import textwrap
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

from backend.mcp.models import MCPResourceSpec, MCPServerConfig, MCPToolSpec
from backend.mcp.registry import MCPRegistry


class _JsonMCPHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802
        if self.path == "/tools":
            self._send_json(
                {
                    "tools": [
                        {
                            "name": "echo_http",
                            "description": "Echo via HTTP JSON",
                            "input_schema": {
                                "type": "object",
                                "properties": {"text": {"type": "string"}},
                                "required": ["text"],
                            },
                            "risk_level": "medium",
                        }
                    ]
                }
            )
            return
        if self.path == "/resources":
            self._send_json(
                {
                    "resources": [
                        {
                            "uri": "memory://club/news",
                            "name": "club-news",
                            "description": "Latest club memory",
                            "mime_type": "text/markdown",
                            "content": "# headline",
                        }
                    ]
                }
            )
            return
        self.send_response(404)
        self.end_headers()

    def do_POST(self) -> None:  # noqa: N802
        if self.path == "/invoke/echo_http":
            size = int(self.headers.get("Content-Length", "0"))
            payload = json.loads(self.rfile.read(size) or b"{}")
            self._send_json(
                {
                    "success": True,
                    "category": "success",
                    "summary": "echo_http completed",
                    "stdout": payload.get("text", ""),
                }
            )
            return
        self.send_response(404)
        self.end_headers()

    def log_message(self, format: str, *args: object) -> None:  # noqa: A003
        return

    def _send_json(self, payload: dict) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


class _SSEMCPHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802
        if self.path == "/tools":
            self._send_sse(
                {
                    "tools": [
                        {
                            "name": "echo_sse",
                            "description": "Echo via HTTP SSE",
                            "input_schema": {
                                "type": "object",
                                "properties": {"text": {"type": "string"}},
                                "required": ["text"],
                            },
                            "risk_level": "medium",
                        }
                    ]
                }
            )
            return
        if self.path == "/resources":
            self._send_sse(
                {
                    "resources": [
                        {
                            "uri": "memory://sse/context",
                            "name": "sse-context",
                            "description": "SSE resource",
                            "mime_type": "text/markdown",
                            "content": "# sse",
                        }
                    ]
                }
            )
            return
        self.send_response(404)
        self.end_headers()

    def do_POST(self) -> None:  # noqa: N802
        if self.path == "/invoke/echo_sse":
            size = int(self.headers.get("Content-Length", "0"))
            payload = json.loads(self.rfile.read(size) or b"{}")
            self._send_sse(
                {
                    "success": True,
                    "category": "success",
                    "summary": "echo_sse completed",
                    "stdout": payload.get("text", ""),
                }
            )
            return
        self.send_response(404)
        self.end_headers()

    def log_message(self, format: str, *args: object) -> None:  # noqa: A003
        return

    def _send_sse(self, payload: dict) -> None:
        body = f"data: {json.dumps(payload)}\n\n".encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


class MCPRegistryTests(unittest.TestCase):
    def test_inline_server_registers_tools_and_resources(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            registry = MCPRegistry(Path(tmp) / "servers.yaml")
            registry.upsert_server(
                MCPServerConfig(
                    name="inline-demo",
                    transport="inline",
                    requires_approval=True,
                    tools=[
                        MCPToolSpec(
                            name="echo_inline",
                            description="Inline echo",
                            input_schema={"type": "object", "properties": {"text": {"type": "string"}}},
                            risk_level="low",
                        )
                    ],
                    resources=[
                        MCPResourceSpec(
                            uri="memory://inline/context",
                            name="inline-context",
                            description="Inline resource",
                            content="demo",
                        )
                    ],
                )
            )

            tools = registry.build_tools()
            status = registry.list_statuses()[0]
            result = asyncio.run(tools[0].run({"text": "hello"}, "session-1"))

            self.assertEqual(len(tools), 1)
            self.assertTrue(tools[0].meta.requires_approval)
            self.assertEqual(tools[0].meta.approval_behavior, "confirmable")
            self.assertEqual(status.status, "connected")
            self.assertEqual(status.tool_count, 1)
            self.assertEqual(status.resource_count, 1)
            self.assertIn("inline-context", registry.describe_resources())
            self.assertTrue(result.success)
            registry.close()

    def test_http_json_server_registers_and_invokes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            server = HTTPServer(("127.0.0.1", 0), _JsonMCPHandler)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            registry = MCPRegistry(Path(tmp) / "servers.yaml")
            registry.upsert_server(
                MCPServerConfig(
                    name="http-demo",
                    transport="http_json",
                    url=f"http://127.0.0.1:{server.server_port}",
                )
            )

            try:
                tools = registry.build_tools()
                result = asyncio.run(tools[0].run({"text": "http"}, "session-2"))

                self.assertEqual(len(tools), 1)
                self.assertEqual(registry.list_resources()[0].uri, "memory://club/news")
                self.assertTrue(result.success)
                self.assertEqual(result.stdout, "http")
            finally:
                registry.close()
                server.shutdown()
                server.server_close()
                thread.join(timeout=2)

    def test_stdio_server_registers_and_invokes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            script_path = root / "stdio_mcp_server.py"
            script_path.write_text(
                textwrap.dedent(
                    """
                    import json
                    import sys

                    for line in sys.stdin:
                        payload = json.loads(line)
                        method = payload.get("method")
                        if method == "tools.list":
                            result = {
                                "tools": [
                                    {
                                        "name": "echo_stdio",
                                        "description": "Echo via stdio",
                                        "input_schema": {
                                            "type": "object",
                                            "properties": {"text": {"type": "string"}},
                                            "required": ["text"],
                                        },
                                        "risk_level": "low",
                                    }
                                ]
                            }
                        elif method == "resources.list":
                            result = {
                                "resources": [
                                    {
                                        "uri": "memory://stdio/context",
                                        "name": "stdio-context",
                                        "description": "Stdio resource",
                                        "content": "abc",
                                    }
                                ]
                            }
                        elif method == "tools.invoke":
                            params = payload.get("params", {})
                            result = {
                                "success": True,
                                "summary": "echo_stdio completed",
                                "stdout": params.get("arguments", {}).get("text", ""),
                            }
                        else:
                            result = {}
                        sys.stdout.write(json.dumps({"id": payload.get("id"), "result": result}) + "\\n")
                        sys.stdout.flush()
                    """
                ).strip()
                + "\n",
                encoding="utf-8",
            )

            registry = MCPRegistry(root / "servers.yaml")
            registry.upsert_server(
                MCPServerConfig(
                    name="stdio-demo",
                    transport="stdio",
                    command=[sys.executable],
                    args=[str(script_path)],
                )
            )

            try:
                tools = registry.build_tools()
                result = asyncio.run(tools[0].run({"text": "stdio"}, "session-3"))

                self.assertEqual(len(tools), 1)
                self.assertEqual(registry.list_resources()[0].name, "stdio-context")
                self.assertTrue(result.success)
                self.assertEqual(result.stdout, "stdio")
            finally:
                registry.close()

    def test_stdio_server_runs_with_workspace_cwd(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            workspace = root / "workspace"
            workspace.mkdir()
            script_path = root / "stdio_mcp_server.py"
            script_path.write_text(
                textwrap.dedent(
                    """
                    import json
                    import os
                    from pathlib import Path
                    import sys

                    for line in sys.stdin:
                        payload = json.loads(line)
                        method = payload.get("method")
                        if method == "tools.list":
                            result = {
                                "tools": [
                                    {
                                        "name": "inspect_workspace",
                                        "description": "Inspect cwd",
                                        "input_schema": {
                                            "type": "object",
                                            "properties": {},
                                        },
                                        "risk_level": "low",
                                    }
                                ]
                            }
                        elif method == "resources.list":
                            result = {"resources": []}
                        elif method == "tools.invoke":
                            result = {
                                "success": True,
                                "summary": "inspect_workspace completed",
                                "stdout": json.dumps(
                                    {
                                        "cwd": str(Path.cwd()),
                                        "workspace_env": os.environ.get("NEWMAN_RUNTIME_WORKSPACE", ""),
                                    }
                                ),
                            }
                        else:
                            result = {}
                        sys.stdout.write(json.dumps({"id": payload.get("id"), "result": result}) + "\\n")
                        sys.stdout.flush()
                    """
                ).strip()
                + "\n",
                encoding="utf-8",
            )

            registry = MCPRegistry(root / "servers.yaml", workspace=workspace)
            registry.upsert_server(
                MCPServerConfig(
                    name="stdio-cwd-demo",
                    transport="stdio",
                    command=[sys.executable],
                    args=[str(script_path)],
                )
            )

            try:
                tools = registry.build_tools()
                result = asyncio.run(tools[0].run({}, "session-stdio-cwd"))
                payload = json.loads(result.stdout)

                self.assertTrue(result.success)
                self.assertEqual(payload["cwd"], str(workspace.resolve()))
                self.assertEqual(payload["workspace_env"], str(workspace.resolve()))
            finally:
                registry.close()

    def test_http_sse_server_registers_and_invokes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            server = HTTPServer(("127.0.0.1", 0), _SSEMCPHandler)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            registry = MCPRegistry(Path(tmp) / "servers.yaml")
            registry.upsert_server(
                MCPServerConfig(
                    name="sse-demo",
                    transport="http_sse",
                    url=f"http://127.0.0.1:{server.server_port}",
                )
            )

            try:
                tools = registry.build_tools()
                result = asyncio.run(tools[0].run({"text": "sse"}, "session-4"))

                self.assertEqual(len(tools), 1)
                self.assertEqual(registry.list_resources()[0].uri, "memory://sse/context")
                self.assertTrue(result.success)
                self.assertEqual(result.stdout, "sse")
            finally:
                registry.close()
                server.shutdown()
                server.server_close()
                thread.join(timeout=2)


if __name__ == "__main__":
    unittest.main()
