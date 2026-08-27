from __future__ import annotations

import asyncio
import json
import subprocess
import threading
from pathlib import Path
from typing import Any
from uuid import uuid4

import httpx

from backend.mcp.models import MCPResourceSpec, MCPServerConfig, MCPToolSpec
from backend.sandbox.environment import sanitize_environment
from backend.sandbox.native_sandbox import NativeSandbox, SandboxUnavailableError


class MCPClientError(RuntimeError):
    def __init__(self, message: str, *, error_code: str = "", metadata: dict[str, object] | None = None) -> None:
        super().__init__(message)
        self.error_code = error_code
        self.metadata = metadata or {}


class StdioSession:
    def __init__(
        self,
        server: MCPServerConfig,
        workspace: Path | None = None,
        sandbox: NativeSandbox | None = None,
    ):
        self.server = server
        self.workspace = workspace.resolve() if workspace is not None else None
        self.sandbox = sandbox
        self.sandboxed = False
        self.filtered_env: list[str] = []
        self.sandbox_metadata: dict[str, object] = {}
        self._process: subprocess.Popen[str] | None = None
        self._lock = threading.Lock()

    def close(self) -> None:
        process = self._process
        self._process = None
        if process is None:
            return
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=2)
        for stream in (process.stdin, process.stdout, process.stderr):
            if stream is not None and not stream.closed:
                stream.close()

    def request(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            process = self._ensure_process()
            request_id = uuid4().hex
            payload = {"id": request_id, "method": method, "params": params}
            assert process.stdin is not None
            process.stdin.write(json.dumps(payload, ensure_ascii=False) + "\n")
            process.stdin.flush()
            assert process.stdout is not None
            while True:
                line = process.stdout.readline()
                if not line:
                    stderr = ""
                    if process.stderr is not None:
                        stderr = process.stderr.read().strip()
                    raise MCPClientError(stderr or f"MCP stdio server {self.server.name} closed the stream")
                response = json.loads(line)
                if response.get("id") != request_id:
                    continue
                if error := response.get("error"):
                    raise MCPClientError(str(error))
                result = response.get("result")
                if not isinstance(result, dict):
                    raise MCPClientError(f"MCP stdio server {self.server.name} returned invalid payload")
                return result

    def _ensure_process(self) -> subprocess.Popen[str]:
        if self._process is not None and self._process.poll() is None:
            return self._process
        command = [*self.server.command, *self.server.args]
        if not command:
            raise MCPClientError(f"MCP stdio server {self.server.name} missing command")
        cwd = self.workspace or Path.cwd()
        readable_roots = _command_readable_roots(command)
        if self.sandbox is not None:
            try:
                command, environment, cwd, self.sandboxed, self.filtered_env = self.sandbox.prepare_argv(
                    command,
                    env=self.server.env,
                    cwd=cwd,
                    mode="read-only",
                    network_access=False,
                    extra_readable_roots=readable_roots,
                )
                self.sandbox_metadata = self.sandbox.execution_metadata(
                    sandboxed=self.sandboxed,
                    mode="read-only",
                    cwd=cwd,
                    network_access=False,
                    runner_started=True,
                    extra_readable_roots=readable_roots,
                    provider_detail="stdio MCP",
                )
            except SandboxUnavailableError as exc:
                raise MCPClientError(
                    f"MCP stdio server {self.server.name} sandbox unavailable [{exc.code}]: {exc.detail}",
                    error_code=exc.code,
                    metadata={
                        "sandboxed": False,
                        "sandbox_transport": "stdio",
                        "sandbox_error_code": exc.code,
                        "sandbox_runner_failed": exc.code in {"SANDBOX_UNAVAILABLE", "SANDBOX_PROBE_FAILED"},
                    },
                ) from exc
        else:
            environment, self.filtered_env = sanitize_environment(
                self.server.env,
                workspace=self.workspace,
            )
            self.sandbox_metadata = {
                "sandboxed": False,
                "sandbox_transport": "stdio",
                "backend": "none",
                "mode": "read-only",
                "file_enforcement": "unsupported",
                "network_enforcement": "unsupported",
                "process_enforcement": "unsupported",
                "resource_enforcement": "unsupported",
                "runner_started": True,
                "runner_failed": False,
            }
        if self.workspace is not None:
            environment.setdefault("NEWMAN_RUNTIME_WORKSPACE", str(self.workspace))
        self._process = subprocess.Popen(
            command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
            env=environment,
            cwd=str(cwd),
        )
        return self._process


class MCPClient:
    def __init__(
        self,
        server: MCPServerConfig,
        workspace: Path | None = None,
        sandbox: NativeSandbox | None = None,
    ):
        self.server = server
        self.workspace = workspace
        self.sandbox = sandbox
        self._stdio: StdioSession | None = (
            StdioSession(server, workspace, sandbox) if server.transport == "stdio" else None
        )
        self.signature = server.model_dump_json()

    def set_sandbox(self, sandbox: NativeSandbox | None) -> None:
        if self.sandbox is sandbox:
            return
        self.close()
        self.sandbox = sandbox
        self._stdio = StdioSession(self.server, self.workspace, sandbox) if self.server.transport == "stdio" else None

    def execution_metadata(self) -> dict[str, object]:
        if self.server.transport in {"http_json", "http_sse"}:
            return {
                "sandboxed": False,
                "sandbox_transport": self.server.transport,
                "sandbox_backend": "remote",
                "sandbox_file_enforcement": "unsupported",
                "sandbox_network_enforcement": "unsupported",
                "sandbox_process_enforcement": "unsupported",
            }
        if self._stdio is None:
            return {"sandboxed": False, "sandbox_transport": self.server.transport}
        return {
            **self._stdio.sandbox_metadata,
            "sandboxed": self._stdio.sandboxed,
            "sandbox_env_filtered": list(self._stdio.filtered_env),
            "sandbox_transport": self.server.transport,
        }

    def close(self) -> None:
        if self._stdio is not None:
            self._stdio.close()

    def list_tools(self) -> list[MCPToolSpec]:
        if self.server.transport == "inline":
            return list(self.server.tools)
        payload = self._request_sync("GET", "/tools")
        items = payload.get("tools", [])
        return [MCPToolSpec.model_validate(item) for item in items]

    def list_resources(self) -> list[MCPResourceSpec]:
        if self.server.transport == "inline":
            return list(self.server.resources)
        payload = self._request_sync("GET", "/resources")
        items = payload.get("resources", [])
        return [MCPResourceSpec.model_validate(item) for item in items]

    async def invoke_tool(self, spec: MCPToolSpec, arguments: dict[str, Any]) -> dict[str, Any]:
        if self.server.transport == "inline":
            return {
                "success": True,
                "category": "success",
                "summary": f"MCP inline tool {spec.name} executed",
                "stdout": f"[mcp:inline] server={self.server.name} tool={spec.name} arguments={arguments}",
                "stderr": "",
                "retryable": False,
            }
        return await self._request_async("POST", f"/invoke/{spec.name}", json_payload=arguments)

    def _request_sync(self, method: str, path: str) -> dict[str, Any]:
        if self.server.transport == "stdio":
            if self._stdio is None:
                raise MCPClientError(f"MCP stdio session unavailable for {self.server.name}")
            stdio_method = "tools.list" if path == "/tools" else "resources.list"
            return self._stdio.request(stdio_method, {})

        if not self.server.url:
            raise MCPClientError(f"MCP server {self.server.name} missing url")

        with httpx.Client(timeout=self.server.timeout_seconds, headers=self.server.headers) as client:
            response = client.request(method, f"{self.server.url.rstrip('/')}{path}")
            response.raise_for_status()
            return self._decode_response_payload(response)

    async def _request_async(self, method: str, path: str, json_payload: dict[str, Any] | None = None) -> dict[str, Any]:
        if self.server.transport == "stdio":
            if self._stdio is None:
                raise MCPClientError(f"MCP stdio session unavailable for {self.server.name}")
            return await asyncio.to_thread(
                self._stdio.request,
                "tools.invoke",
                {"tool": path.rsplit("/", 1)[-1], "arguments": json_payload or {}},
            )

        if not self.server.url:
            raise MCPClientError(f"MCP server {self.server.name} missing url")

        async with httpx.AsyncClient(timeout=self.server.timeout_seconds, headers=self.server.headers) as client:
            if self.server.transport == "http_sse":
                async with client.stream(method, f"{self.server.url.rstrip('/')}{path}", json=json_payload) as response:
                    response.raise_for_status()
                    body = await response.aread()
                    return self._decode_raw_payload(body, response.headers.get("content-type", ""))

            response = await client.request(method, f"{self.server.url.rstrip('/')}{path}", json=json_payload)
            response.raise_for_status()
            return self._decode_response_payload(response)

    def _decode_response_payload(self, response: httpx.Response) -> dict[str, Any]:
        return self._decode_raw_payload(response.content, response.headers.get("content-type", ""))

    def _decode_raw_payload(self, payload: bytes, content_type: str) -> dict[str, Any]:
        text = payload.decode("utf-8")
        if "text/event-stream" in content_type:
            return self._parse_sse_payload(text)
        data = json.loads(text or "{}")
        if not isinstance(data, dict):
            raise MCPClientError(f"MCP server {self.server.name} returned non-object payload")
        return data

    def _parse_sse_payload(self, payload: str) -> dict[str, Any]:
        collected: list[str] = []
        for line in payload.splitlines():
            if line.startswith("data:"):
                collected.append(line[5:].strip())
        body = "\n".join(part for part in collected if part and part != "[DONE]").strip()
        if not body:
            return {}
        data = json.loads(body)
        if not isinstance(data, dict):
            raise MCPClientError(f"MCP SSE server {self.server.name} returned non-object payload")
        return data


def _command_readable_roots(command: list[str]) -> list[Path]:
    roots: list[Path] = []
    for value in command:
        path = Path(value)
        if not path.is_absolute() or not path.exists():
            continue
        roots.append(path if path.is_dir() else path.parent)
    deduped: list[Path] = []
    seen: set[str] = set()
    for root in roots:
        resolved = root.resolve()
        key = str(resolved)
        if key not in seen:
            seen.add(key)
            deduped.append(resolved)
    return deduped
