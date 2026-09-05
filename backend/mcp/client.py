from __future__ import annotations

import asyncio
import json
import subprocess
import threading
from pathlib import Path
from typing import Any
from urllib.parse import urljoin
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
        self._mcp_http_initialized = False
        self._mcp_http_session_id: str | None = None
        self.signature = server.model_dump_json()

    def set_sandbox(self, sandbox: NativeSandbox | None) -> None:
        if self.sandbox is sandbox:
            return
        self.close()
        self.sandbox = sandbox
        self._stdio = StdioSession(self.server, self.workspace, sandbox) if self.server.transport == "stdio" else None

    def execution_metadata(self) -> dict[str, object]:
        if self.server.transport in {"http_json", "http_sse", "mcp_http", "mcp_sse"}:
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
        if self.server.transport in {"mcp_http", "mcp_sse"}:
            payload = self._mcp_http_request_sync("tools/list", {})
            items = payload.get("tools", [])
            return [_normalize_mcp_http_tool_spec(item) for item in items]
        payload = self._request_sync("GET", "/tools")
        items = payload.get("tools", [])
        return [MCPToolSpec.model_validate(item) for item in items]

    def list_resources(self) -> list[MCPResourceSpec]:
        if self.server.transport == "inline":
            return list(self.server.resources)
        if self.server.transport in {"mcp_http", "mcp_sse"}:
            try:
                payload = self._mcp_http_request_sync("resources/list", {})
            except (MCPClientError, httpx.HTTPStatusError) as exc:
                if isinstance(exc, httpx.HTTPStatusError) or exc.metadata.get("jsonrpc_code") in {-32601, -32603}:
                    return []
                raise
            items = payload.get("resources", [])
            return [_normalize_mcp_http_resource_spec(item) for item in items]
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
        if self.server.transport in {"mcp_http", "mcp_sse"}:
            return await self._mcp_http_request_async("tools/call", {"name": spec.name, "arguments": arguments})
        return await self._request_async("POST", f"/invoke/{spec.name}", json_payload=arguments)

    def _mcp_http_headers(self) -> dict[str, str]:
        headers = dict(self.server.headers)
        headers.setdefault("Accept", "application/json, text/event-stream")
        headers.setdefault("MCP-Protocol-Version", "2024-11-05")
        if self._mcp_http_session_id:
            headers.setdefault("Mcp-Session-Id", self._mcp_http_session_id)
        return headers

    def _ensure_mcp_http_initialized_sync(self) -> None:
        if self._mcp_http_initialized:
            return
        self._mcp_http_request_sync(
            "initialize",
            {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "newman", "version": "0.1.0"},
            },
            initialize=False,
        )
        self._mcp_http_initialized = True
        self._mcp_http_notify_sync("notifications/initialized", {})

    def _mcp_http_request_sync(
        self,
        method: str,
        params: dict[str, Any] | None = None,
        *,
        initialize: bool = True,
    ) -> dict[str, Any]:
        if not self.server.url:
            raise MCPClientError(f"MCP server {self.server.name} missing url")
        if self.server.transport == "mcp_sse":
            return self._mcp_sse_request_sync(method, params or {}, initialize=initialize)
        if initialize:
            self._ensure_mcp_http_initialized_sync()
        request_id = uuid4().hex
        payload = {"jsonrpc": "2.0", "id": request_id, "method": method, "params": params or {}}
        with httpx.Client(timeout=self.server.timeout_seconds, headers=self._mcp_http_headers()) as client:
            response = client.post(self.server.url, json=payload)
            if session_id := response.headers.get("mcp-session-id"):
                self._mcp_http_session_id = session_id
            self._raise_mcp_http_status(response, method)
            data = self._decode_response_payload(response)
        return self._extract_mcp_http_result(method, data)

    def _mcp_http_notify_sync(self, method: str, params: dict[str, Any] | None = None) -> None:
        if not self.server.url:
            return
        if self.server.transport == "mcp_sse":
            return
        payload = {"jsonrpc": "2.0", "method": method, "params": params or {}}
        try:
            with httpx.Client(timeout=self.server.timeout_seconds, headers=self._mcp_http_headers()) as client:
                response = client.post(self.server.url, json=payload)
                if session_id := response.headers.get("mcp-session-id"):
                    self._mcp_http_session_id = session_id
                response.raise_for_status()
        except Exception:
            return

    async def _mcp_http_request_async(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        if not self.server.url:
            raise MCPClientError(f"MCP server {self.server.name} missing url")
        if self.server.transport == "mcp_sse":
            result = await asyncio.to_thread(self._mcp_sse_request_sync, method, params or {}, True)
            if method == "tools/call":
                return _format_mcp_http_tool_result(params or {}, result)
            return result
        if not self._mcp_http_initialized:
            await asyncio.to_thread(self._ensure_mcp_http_initialized_sync)
        request_id = uuid4().hex
        payload = {"jsonrpc": "2.0", "id": request_id, "method": method, "params": params or {}}
        async with httpx.AsyncClient(timeout=self.server.timeout_seconds, headers=self._mcp_http_headers()) as client:
            response = await client.post(self.server.url, json=payload)
            if session_id := response.headers.get("mcp-session-id"):
                self._mcp_http_session_id = session_id
            self._raise_mcp_http_status(response, method)
            data = self._decode_response_payload(response)
        result = self._extract_mcp_http_result(method, data)
        if method == "tools/call":
            return _format_mcp_http_tool_result(params or {}, result)
        return result

    def _mcp_sse_request_sync(
        self,
        method: str,
        params: dict[str, Any] | None = None,
        initialize: bool = True,
    ) -> dict[str, Any]:
        if not self.server.url:
            raise MCPClientError(f"MCP server {self.server.name} missing url")
        headers = dict(self.server.headers)
        headers.setdefault("Accept", "text/event-stream")
        with httpx.Client(timeout=self.server.timeout_seconds, headers=headers) as stream_client:
            with stream_client.stream("GET", self.server.url) as stream:
                stream.raise_for_status()
                events = _iter_sse_events(stream.iter_lines())
                endpoint_url = self._read_mcp_sse_endpoint(events)
                post_client = httpx.Client(timeout=self.server.timeout_seconds)
                try:
                    if initialize:
                        initialize_id = uuid4().hex
                        self._post_mcp_sse_jsonrpc(
                            post_client,
                            endpoint_url,
                            {
                                "jsonrpc": "2.0",
                                "id": initialize_id,
                                "method": "initialize",
                                "params": {
                                    "protocolVersion": "2024-11-05",
                                    "capabilities": {},
                                    "clientInfo": {"name": "newman", "version": "0.1.0"},
                                },
                            },
                        )
                        self._read_mcp_sse_response(events, initialize_id, "initialize")
                        self._post_mcp_sse_jsonrpc(
                            post_client,
                            endpoint_url,
                            {"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}},
                            expect_response=False,
                        )

                    request_id = uuid4().hex
                    self._post_mcp_sse_jsonrpc(
                        post_client,
                        endpoint_url,
                        {"jsonrpc": "2.0", "id": request_id, "method": method, "params": params or {}},
                    )
                    return self._read_mcp_sse_response(events, request_id, method)
                finally:
                    post_client.close()

    def _read_mcp_sse_endpoint(self, events: Any) -> str:
        for event in events:
            if event.get("event") != "endpoint":
                continue
            endpoint = str(event.get("data") or "").strip()
            if not endpoint:
                break
            return urljoin(self.server.url or "", endpoint)
        raise MCPClientError(f"MCP SSE server {self.server.name} did not advertise a message endpoint")

    def _post_mcp_sse_jsonrpc(
        self,
        client: httpx.Client,
        endpoint_url: str,
        payload: dict[str, Any],
        *,
        expect_response: bool = True,
    ) -> None:
        headers = dict(self.server.headers)
        headers.setdefault("Accept", "application/json")
        response = client.post(endpoint_url, json=payload, headers=headers)
        if response.status_code == 202:
            return
        if expect_response or response.is_error:
            response.raise_for_status()

    def _read_mcp_sse_response(self, events: Any, request_id: str, method: str) -> dict[str, Any]:
        for event in events:
            if event.get("event", "message") != "message":
                continue
            raw_data = str(event.get("data") or "")
            try:
                data = json.loads(raw_data)
            except json.JSONDecodeError:
                continue
            if not isinstance(data, dict):
                raise MCPClientError(f"MCP SSE {method} returned non-object payload")
            if data.get("id") != request_id:
                continue
            return self._extract_mcp_http_result(method, data)
        raise MCPClientError(f"MCP SSE {method} did not return a response")

    def _raise_mcp_http_status(self, response: httpx.Response, method: str) -> None:
        if not response.is_error:
            return
        try:
            data = self._decode_response_payload(response)
            self._extract_mcp_http_result(method, data)
        except MCPClientError:
            raise
        except Exception:
            pass
        response.raise_for_status()

    def _extract_mcp_http_result(self, method: str, data: dict[str, Any]) -> dict[str, Any]:
        error = data.get("error")
        if error:
            error_code = error.get("code") if isinstance(error, dict) else None
            raise MCPClientError(
                f"MCP JSON-RPC {method} failed: {error}",
                metadata={"jsonrpc_code": error_code} if error_code is not None else {},
            )
        result = data.get("result", {})
        if not isinstance(result, dict):
            raise MCPClientError(f"MCP JSON-RPC {method} returned invalid result")
        return result

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
        try:
            data = json.loads(body)
        except json.JSONDecodeError:
            data = None
            for part in reversed(collected):
                if not part or part == "[DONE]":
                    continue
                try:
                    data = json.loads(part)
                    break
                except json.JSONDecodeError:
                    continue
            if data is None:
                raise
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


def _iter_sse_events(lines: Any):
    event_name = "message"
    data_lines: list[str] = []
    for line in lines:
        if line == "":
            if data_lines:
                yield {"event": event_name, "data": "\n".join(data_lines)}
            event_name = "message"
            data_lines = []
            continue
        if line.startswith(":"):
            continue
        if line.startswith("event:"):
            event_name = line[6:].strip() or "message"
            continue
        if line.startswith("data:"):
            data_lines.append(line[5:].lstrip())
    if data_lines:
        yield {"event": event_name, "data": "\n".join(data_lines)}


def _normalize_mcp_http_tool_spec(item: Any) -> MCPToolSpec:
    if not isinstance(item, dict):
        raise MCPClientError("MCP tools/list returned non-object tool spec")
    input_schema = item.get("input_schema") or item.get("inputSchema") or {"type": "object", "properties": {}}
    if not isinstance(input_schema, dict):
        input_schema = {"type": "object", "properties": {}}
    risk_level = item.get("risk_level") or item.get("riskLevel") or "medium"
    if risk_level not in {"low", "medium", "high", "critical"}:
        risk_level = "medium"
    return MCPToolSpec(
        name=str(item.get("name") or ""),
        description=str(item.get("description") or item.get("title") or ""),
        input_schema=input_schema,
        risk_level=risk_level,
    )


def _normalize_mcp_http_resource_spec(item: Any) -> MCPResourceSpec:
    if not isinstance(item, dict):
        raise MCPClientError("MCP resources/list returned non-object resource spec")
    return MCPResourceSpec(
        uri=str(item.get("uri") or ""),
        name=str(item.get("name") or item.get("uri") or ""),
        description=str(item.get("description") or ""),
        mime_type=item.get("mime_type") or item.get("mimeType"),
        content=str(item.get("content") or ""),
    )


def _format_mcp_http_tool_result(params: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
    if "success" in result or "stdout" in result or "stderr" in result:
        return result
    is_error = bool(result.get("isError"))
    stdout = _render_mcp_http_content(result.get("content"))
    structured_content = result.get("structuredContent")
    if structured_content is not None:
        structured_text = json.dumps(structured_content, ensure_ascii=False, indent=2)
        stdout = f"{stdout}\n{structured_text}".strip() if stdout else structured_text
    tool_name = str(params.get("name") or "MCP tool")
    return {
        "success": not is_error,
        "category": "runtime_error" if is_error else "success",
        "summary": f"MCP tool {tool_name} {'failed' if is_error else 'executed'}",
        "stdout": stdout,
        "stderr": stdout if is_error else "",
        "retryable": False,
    }


def _render_mcp_http_content(content: Any) -> str:
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return "" if content is None else json.dumps(content, ensure_ascii=False, indent=2)
    rendered: list[str] = []
    for item in content:
        if not isinstance(item, dict):
            rendered.append(str(item))
            continue
        if item.get("type") == "text" and isinstance(item.get("text"), str):
            rendered.append(item["text"])
        elif item.get("type") == "resource":
            rendered.append(json.dumps(item.get("resource", item), ensure_ascii=False, indent=2))
        else:
            rendered.append(json.dumps(item, ensure_ascii=False, indent=2))
    return "\n".join(part for part in rendered if part).strip()
