from __future__ import annotations

import asyncio
import json
import os
import sys
import tempfile
import textwrap
import types
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

fake_psycopg = types.ModuleType("psycopg")
fake_psycopg.connect = lambda *args, **kwargs: None
fake_rows = types.ModuleType("psycopg.rows")
fake_rows.dict_row = object()
fake_types = types.ModuleType("psycopg.types")
fake_json = types.ModuleType("psycopg.types.json")
fake_json.Jsonb = lambda value: value
fake_chromadb = types.ModuleType("chromadb")


class _FakeCollection:
    def upsert(self, *args, **kwargs):
        return None

    def delete(self, *args, **kwargs):
        return None

    def query(self, *args, **kwargs):
        return {"ids": [[]], "distances": [[]], "metadatas": [[]], "documents": [[]]}


class _FakePersistentClient:
    def __init__(self, *args, **kwargs):
        pass

    def get_or_create_collection(self, *args, **kwargs):
        return _FakeCollection()


fake_chromadb.PersistentClient = _FakePersistentClient
sys.modules.setdefault("psycopg", fake_psycopg)
sys.modules.setdefault("psycopg.rows", fake_rows)
sys.modules.setdefault("psycopg.types", fake_types)
sys.modules.setdefault("psycopg.types.json", fake_json)
sys.modules.setdefault("chromadb", fake_chromadb)

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.api.middleware.error_handler import install_error_handlers
from backend.api.routes.approvals import router as approvals_router
from backend.api.routes.config import router as config_router
from backend.api.routes.knowledge import router as knowledge_router
from backend.api.routes.messages import ActiveSessionRun, router as messages_router
from backend.api.routes.plugins import router as plugins_router
from backend.api.routes.sessions import router as sessions_router
from backend.api.routes.skills import router as skills_router
from backend.api.routes.tools import router as tools_router
from backend.api.routes.workspace import router as workspace_router
from backend.config.schema import AppConfig
from backend.config.loader import reload_settings
from backend.plugin_runtime.service import PluginService
from backend.providers.base import ProviderError
from backend.rag.models import KnowledgeDocument
from backend.sessions.models import SessionMessage
from backend.sessions.session_store import SessionStore
from backend.skill_runtime.registry import SkillRegistry
from backend.tools.approval import ApprovalManager, ApprovalRequest
from backend.tools.base import BaseTool, ToolMeta
from backend.tools.impl.read_file import ReadFileTool
from backend.tools.result import ToolExecutionResult
from backend.tools.workspace_fs import PathAccessPolicy


class _DummySessionStore:
    def get(self, session_id: str) -> dict:
        return {"session_id": session_id}


class _DummyMultimodalAnalyzer:
    def __init__(self, *, should_fail: bool = False):
        self.should_fail = should_fail

    async def parse_user_input(
        self,
        content: str,
        paths: list[Path],
        *,
        session_id: str | None = None,
        turn_id: str | None = None,
    ) -> dict:
        if self.should_fail:
            raise ProviderError("openai_compatible", "timeout_error", "OpenAI-compatible request timed out", True)
        return {
            "schema_version": "v1",
            "status": "completed",
            "parser_provider": "openai_compatible",
            "parser_model": "dummy-mm",
            "normalized_user_input": "结合图片理解用户意图",
            "task_intent": "describe_uploaded_images",
            "key_facts": [f"image:{path.name}" for path in paths],
            "ocr_text": [],
            "uncertainties": [],
            "attachment_summaries": [f"image:{path.name}" for path in paths],
        }

    async def analyze_images(
        self,
        content: str,
        paths: list[Path],
        *,
        session_id: str | None = None,
        turn_id: str | None = None,
    ) -> list[dict]:
        parsed = await self.parse_user_input(content, paths, session_id=session_id, turn_id=turn_id)
        return [{"summary": summary} for summary in parsed["attachment_summaries"]]


class _DummyMessageRuntime:
    def __init__(self):
        self.session_store = _DummySessionStore()
        self.multimodal_analyzer = _DummyMultimodalAnalyzer()
        self.calls: list[dict] = []

    async def handle_message(
        self,
        session_id: str,
        content: str,
        emit,
        user_metadata: dict[str, object] | None = None,
        turn_approval_mode: str = "manual",
        request_id: str | None = None,
        turn_id: str | None = None,
        on_turn_created=None,
        post_user_message=None,
    ) -> None:
        self.calls.append(
            {
                "session_id": session_id,
                "content": content,
                "user_metadata": user_metadata,
                "turn_approval_mode": turn_approval_mode,
                "request_id": request_id,
            }
        )
        if callable(on_turn_created):
            on_turn_created(turn_id or "dummy-turn")
        await emit(
            "final_response",
            {
                "session_id": session_id,
                "content": "ok",
                "finish_reason": "stop",
            },
        )


class _PersistingMessageRuntime:
    def __init__(self, session_store: SessionStore, multimodal_analyzer: _DummyMultimodalAnalyzer):
        self.session_store = session_store
        self.multimodal_analyzer = multimodal_analyzer
        self.settings = SimpleNamespace(models=SimpleNamespace(multimodal=SimpleNamespace(timeout=120)))

    async def handle_message(
        self,
        session_id: str,
        content: str,
        emit,
        user_metadata: dict[str, object] | None = None,
        turn_approval_mode: str = "manual",
        request_id: str | None = None,
        turn_id: str | None = None,
        on_turn_created=None,
        post_user_message=None,
    ) -> None:
        resolved_turn_id = turn_id or "dummy-turn"
        message = SessionMessage(
            id=resolved_turn_id,
            role="user",
            content=content,
            metadata={
                "turn_id": resolved_turn_id,
                **({"request_id": request_id} if request_id else {}),
                **(user_metadata or {}),
            },
        )
        session = self.session_store.append_message(session_id, message)
        if callable(on_turn_created):
            on_turn_created(resolved_turn_id)
        task = SimpleNamespace(session=session, turn_id=resolved_turn_id)
        if callable(post_user_message):
            await post_user_message(task, message, emit)

        assistant = SessionMessage(
            id=f"assistant-{resolved_turn_id}",
            role="assistant",
            content="ok",
            metadata={"turn_id": resolved_turn_id},
        )
        session.messages.append(assistant)
        self.session_store.save(session)
        await emit(
            "final_response",
            {
                "session_id": session_id,
                "content": "ok",
                "finish_reason": "stop",
            },
        )


class _DummyTool:
    def __init__(self, name: str):
        self.meta = SimpleNamespace(name=name)


class _DummyRegistry:
    def __init__(self, tool_names: list[str]):
        self._tool_names = tool_names

    def list_tools(self) -> list[_DummyTool]:
        return [_DummyTool(name) for name in self._tool_names]


class _DummyMCPRegistry:
    def build_tools(self, plugin_configs=None):
        return []


class _DummyContextProvider:
    async def chat(self, messages, tools=None, **kwargs):
        raise AssertionError("chat should not be called in this test")

    async def chat_stream(self, messages, tools=None, **kwargs):
        raise AssertionError("chat_stream should not be called in this test")

    def estimate_tokens(self, messages) -> int:
        return 0


class _SkillRuntime:
    def __init__(self, plugin_service: PluginService, memory_dir: Path, tool_names: list[str]):
        self.plugin_service = plugin_service
        self.skill_registry = SkillRegistry(plugin_service, memory_dir)
        self.registry = _DummyRegistry(tool_names)
        self.mcp_registry = _DummyMCPRegistry()

    def reload_ecosystem(self) -> None:
        self.plugin_service.reload()
        self.skill_registry.sync_snapshot()


def _build_app(router, *, runtime=None, settings=None, project_root=None, scheduler=None, channels=None) -> FastAPI:
    app = FastAPI()
    app.state.runtime = runtime or SimpleNamespace()
    app.state.settings = settings or SimpleNamespace()
    app.state.project_root = project_root
    app.state.scheduler = scheduler or SimpleNamespace()
    app.state.channels = channels or SimpleNamespace()
    install_error_handlers(app)
    app.include_router(router)
    return app


def _write_plugin(root: Path, name: str, manifest: str, *, skill_dir_name: str = "plugin_skill", skill_body: str | None = None) -> None:
    plugin_dir = root / name
    plugin_dir.mkdir(parents=True, exist_ok=True)
    (plugin_dir / "plugin.yaml").write_text(textwrap.dedent(manifest).strip() + "\n", encoding="utf-8")
    if skill_body is not None:
        skill_dir = plugin_dir / "skills" / skill_dir_name
        skill_dir.mkdir(parents=True, exist_ok=True)
        (skill_dir / "SKILL.md").write_text(skill_body, encoding="utf-8")


def _write_config_project(root: Path, project_config: str) -> None:
    config_dir = root / "backend" / "config"
    config_dir.mkdir(parents=True, exist_ok=True)
    defaults_source = Path(__file__).resolve().parents[1] / "config" / "defaults.yaml"
    (config_dir / "defaults.yaml").write_text(defaults_source.read_text(encoding="utf-8"), encoding="utf-8")
    (root / "newman.yaml").write_text(textwrap.dedent(project_config).strip() + "\n", encoding="utf-8")


class MessageRouteTests(unittest.TestCase):
    def _parse_sse_events(self, response) -> list[dict]:
        return [
            json.loads(line.removeprefix("data: ").strip())
            for line in response.text.splitlines()
            if line.startswith("data: ")
        ]

    def test_messages_json_parses_approval_mode(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            runtime = _DummyMessageRuntime()
            settings = SimpleNamespace(paths=SimpleNamespace(audit_dir=root / "audit", data_dir=root / "data"))
            client = TestClient(_build_app(messages_router, runtime=runtime, settings=settings))

            response = client.post(
                "/api/sessions/session-1/messages",
                json={"content": "hello", "approval_mode": "auto_allow"},
            )

            self.assertEqual(response.status_code, 200)
            self.assertEqual(runtime.calls[0]["turn_approval_mode"], "auto_allow")
            self.assertEqual(runtime.calls[0]["user_metadata"]["approval_mode"], "auto_allow")

    def test_messages_json_accepts_legacy_auto_approve_level2_alias(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            runtime = _DummyMessageRuntime()
            settings = SimpleNamespace(paths=SimpleNamespace(audit_dir=root / "audit", data_dir=root / "data"))
            client = TestClient(_build_app(messages_router, runtime=runtime, settings=settings))

            response = client.post(
                "/api/sessions/session-1/messages",
                json={"content": "hello", "approval_mode": "auto_approve_level2"},
            )

            self.assertEqual(response.status_code, 200)
            self.assertEqual(runtime.calls[0]["turn_approval_mode"], "auto_allow")
            self.assertEqual(runtime.calls[0]["user_metadata"]["approval_mode"], "auto_allow")

    def test_messages_form_defaults_approval_mode_to_manual(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            runtime = _DummyMessageRuntime()
            settings = SimpleNamespace(paths=SimpleNamespace(audit_dir=root / "audit", data_dir=root / "data"))
            client = TestClient(_build_app(messages_router, runtime=runtime, settings=settings))

            response = client.post(
                "/api/sessions/session-1/messages",
                data={"content": "hello from form"},
            )

            self.assertEqual(response.status_code, 200)
            self.assertEqual(runtime.calls[0]["turn_approval_mode"], "manual")
            self.assertEqual(runtime.calls[0]["user_metadata"]["approval_mode"], "manual")

    def test_messages_with_image_updates_user_message_after_analysis(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            session_store = SessionStore(root / "sessions")
            session = session_store.create(title="image-turn")
            runtime = _PersistingMessageRuntime(session_store, _DummyMultimodalAnalyzer())
            settings = SimpleNamespace(paths=SimpleNamespace(audit_dir=root / "audit", data_dir=root / "data"))
            client = TestClient(_build_app(messages_router, runtime=runtime, settings=settings))

            response = client.post(
                f"/api/sessions/{session.session_id}/messages",
                data={"content": "看看这张图"},
                files={"images": ("demo.png", b"fake-png", "image/png")},
            )

            self.assertEqual(response.status_code, 200)
            saved = session_store.get(session.session_id)
            self.assertEqual(saved.messages[0].role, "user")
            self.assertEqual(saved.messages[0].content, "看看这张图")
            self.assertEqual(saved.messages[0].metadata["original_content"], "看看这张图")
            self.assertEqual(saved.messages[0].metadata["attachments"][0]["analysis_status"], "completed")
            self.assertEqual(saved.messages[0].metadata["multimodal_parse"]["status"], "completed")
            self.assertEqual(saved.messages[0].metadata["multimodal_parse"]["normalized_user_input"], "结合图片理解用户意图")
            self.assertEqual(saved.messages[-1].role, "assistant")

            events = self._parse_sse_events(response)
            processed = next(payload for payload in events if payload["event"] == "attachment_processed")
            self.assertTrue(processed["data"]["ok"])

    def test_messages_with_image_timeout_keeps_turn_and_records_warning(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            session_store = SessionStore(root / "sessions")
            session = session_store.create(title="image-timeout")
            runtime = _PersistingMessageRuntime(session_store, _DummyMultimodalAnalyzer(should_fail=True))
            settings = SimpleNamespace(paths=SimpleNamespace(audit_dir=root / "audit", data_dir=root / "data"))
            client = TestClient(_build_app(messages_router, runtime=runtime, settings=settings))

            response = client.post(
                f"/api/sessions/{session.session_id}/messages",
                data={"content": "看看这张图"},
                files={"images": ("demo.png", b"fake-png", "image/png")},
            )

            self.assertEqual(response.status_code, 200)
            saved = session_store.get(session.session_id)
            self.assertEqual(saved.messages[0].role, "user")
            self.assertEqual(saved.messages[0].content, "看看这张图")
            self.assertEqual(saved.messages[0].metadata["attachments"][0]["analysis_status"], "failed")
            self.assertEqual(saved.messages[0].metadata["multimodal_parse"]["status"], "failed")
            self.assertEqual(saved.messages[0].metadata["multimodal_parse"]["frontend_message"], "图片预解析超时，已跳过图片内容解析")
            self.assertEqual(saved.messages[1].role, "system")
            self.assertEqual(saved.messages[1].metadata["type"], "attachment_analysis_warning")
            self.assertEqual(saved.messages[-1].role, "assistant")

            events = self._parse_sse_events(response)
            processed = next(payload for payload in events if payload["event"] == "attachment_processed")
            self.assertFalse(processed["data"]["ok"])
            self.assertEqual(processed["data"]["category"], "timeout_error")
            self.assertTrue(any(payload["event"] == "final_response" for payload in events))

    def test_interrupt_route_persists_turn_interrupted_event(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            session_store = SessionStore(root / "sessions")
            session = session_store.create(title="interrupt-me")
            request_id = "req-interrupt"
            turn_id = "turn-interrupt"
            session.messages.append(
                SessionMessage(
                    id="user-1",
                    role="user",
                    content="处理中",
                    metadata={"turn_id": turn_id, "request_id": request_id},
                )
            )
            session_store.save(session)

            class _InterruptWorker:
                def __init__(self) -> None:
                    self.cancelled = False

                def done(self) -> bool:
                    return False

                def cancel(self) -> None:
                    self.cancelled = True

                def __await__(self):
                    async def _wait():
                        raise asyncio.CancelledError

                    return _wait().__await__()

            worker = _InterruptWorker()
            event_queue: asyncio.Queue[bytes] = asyncio.Queue()
            runtime = SimpleNamespace(session_store=session_store)
            settings = SimpleNamespace(paths=SimpleNamespace(audit_dir=root / "audit", data_dir=root / "data"))
            client = TestClient(_build_app(messages_router, runtime=runtime, settings=settings))
            client.app.state.active_message_runs = {
                session.session_id: ActiveSessionRun(
                    session_id=session.session_id,
                    request_id=request_id,
                    worker=worker,
                    event_queue=event_queue,
                    turn_id=turn_id,
                )
            }

            response = client.post(f"/api/sessions/{session.session_id}/interrupt")

            self.assertEqual(response.status_code, 200)
            payload = response.json()
            self.assertTrue(payload["interrupted"])
            self.assertEqual(payload["turn_id"], turn_id)
            self.assertTrue(worker.cancelled)
            self.assertNotIn(session.session_id, client.app.state.active_message_runs)

            saved = session_store.get(session.session_id)
            self.assertEqual(saved.messages[-1].role, "system")
            self.assertEqual(saved.messages[-1].metadata["type"], "turn_interrupted")
            self.assertEqual(saved.messages[-1].metadata["turn_id"], turn_id)

            audit_lines = (root / "audit" / f"{session.session_id}.log").read_text(encoding="utf-8").splitlines()
            self.assertTrue(audit_lines)
            event_payload = json.loads(audit_lines[-1])
            self.assertEqual(event_payload["event"], "turn_interrupted")
            self.assertEqual(event_payload["data"]["turn_id"], turn_id)

            queued_payload = json.loads(event_queue.get_nowait().decode("utf-8").removeprefix("data: ").strip())
            self.assertEqual(queued_payload["event"], "turn_interrupted")
            self.assertEqual(queued_payload["data"]["turn_id"], turn_id)


class ApprovalRouteTests(unittest.TestCase):
    def test_approve_and_reject_contracts(self) -> None:
        approvals = ApprovalManager()
        request = ApprovalRequest(
            approval_request_id="apr-1",
            session_id="session-1",
            turn_id="turn-1",
            tool_name="terminal",
            arguments={"command": "pwd"},
            reason="terminal_mutation_or_unknown",
        )
        approvals._pending[request.approval_request_id] = request
        runtime = SimpleNamespace(
            approvals=approvals,
            settings=SimpleNamespace(approval=SimpleNamespace(timeout_seconds=120)),
        )
        client = TestClient(_build_app(approvals_router, runtime=runtime))

        pending = client.get("/api/sessions/session-1/pending-approval")
        self.assertEqual(pending.status_code, 200)
        self.assertEqual(pending.json()["pending"]["approval_request_id"], request.approval_request_id)

        approved = client.post(
            "/api/sessions/session-1/approve",
            json={"approval_request_id": request.approval_request_id},
        )
        self.assertEqual(approved.status_code, 200)
        self.assertTrue(approved.json()["approved"])

        second = ApprovalRequest(
            approval_request_id="apr-2",
            session_id="session-2",
            turn_id="turn-2",
            tool_name="terminal",
            arguments={"command": "pwd"},
            reason="terminal_mutation_or_unknown",
        )
        approvals._pending[second.approval_request_id] = second
        rejected = client.post(
            "/api/sessions/session-2/reject",
            json={"approval_request_id": second.approval_request_id},
        )
        self.assertEqual(rejected.status_code, 200)
        self.assertFalse(rejected.json()["approved"])

    def test_approve_validation_and_session_conflict(self) -> None:
        approvals = ApprovalManager()
        request = ApprovalRequest(
            approval_request_id="apr-3",
            session_id="session-2",
            turn_id="turn-3",
            tool_name="terminal",
            arguments={"command": "pwd"},
            reason="terminal_mutation_or_unknown",
        )
        approvals._pending[request.approval_request_id] = request
        runtime = SimpleNamespace(
            approvals=approvals,
            settings=SimpleNamespace(approval=SimpleNamespace(timeout_seconds=120)),
        )
        client = TestClient(_build_app(approvals_router, runtime=runtime))

        missing = client.post("/api/sessions/session-1/approve", json={})
        self.assertEqual(missing.status_code, 422)

        conflict = client.post(
            "/api/sessions/session-1/approve",
            json={"approval_request_id": request.approval_request_id},
        )
        self.assertEqual(conflict.status_code, 409)


class SkillsRouteTests(unittest.TestCase):
    def test_skill_crud_and_readonly_guards(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plugins_dir = root / "plugins"
            skills_dir = root / "skills"
            memory_dir = root / "memory"
            state_path = root / "state" / "plugin_state.json"
            plugins_dir.mkdir(parents=True, exist_ok=True)
            skills_dir.mkdir(parents=True, exist_ok=True)
            memory_dir.mkdir(parents=True, exist_ok=True)

            workspace_skill_dir = skills_dir / "writer"
            workspace_skill_dir.mkdir(parents=True, exist_ok=True)
            (workspace_skill_dir / "SKILL.md").write_text(
                textwrap.dedent(
                    """\
                    ---
                    name: writer
                    description: Write and refine deliverables.
                    ---

                    ## Workflow

                    1. Use `read_file` first.
                    2. Then use `write_file`.

                    ## Constraints

                    - Do not modify unrelated files.
                    - Only change what is required.
                    """
                ),
                encoding="utf-8",
            )

            source_skill_dir = root / "imports" / "reviewer"
            source_skill_dir.mkdir(parents=True, exist_ok=True)
            (source_skill_dir / "SKILL.md").write_text(
                textwrap.dedent(
                    """\
                    ---
                    name: reviewer
                    description: Review a change.
                    ---

                    Review things carefully.
                    """
                ),
                encoding="utf-8",
            )

            invalid_skill_dir = root / "imports" / "broken"
            invalid_skill_dir.mkdir(parents=True, exist_ok=True)

            _write_plugin(
                plugins_dir,
                "demo_plugin",
                """
                name: demo-plugin
                version: 1.0.0
                description: Demo plugin
                """,
                skill_body="---\nname: plugin-review\n---\nUse `read_file` only.\n",
            )

            service = PluginService(plugins_dir, skills_dir, state_path)
            runtime = _SkillRuntime(service, memory_dir, ["read_file", "write_file", "search_files"])
            settings = SimpleNamespace(paths=SimpleNamespace(workspace=root))
            client = TestClient(_build_app(skills_router, runtime=runtime, settings=settings))

            detail = client.get("/api/skills/writer")
            self.assertEqual(detail.status_code, 200)
            payload = detail.json()["skill"]
            self.assertEqual(payload["name"], "writer")
            self.assertFalse(payload["readonly"])
            self.assertIn("read_file", payload["tool_dependencies"])
            self.assertIn("Do not modify unrelated files.", payload["usage_limits_summary"])

            imported = client.post("/api/skills/import", json={"source_path": "imports/reviewer"})
            self.assertEqual(imported.status_code, 200)
            self.assertTrue((skills_dir / "reviewer" / "SKILL.md").exists())
            self.assertEqual(imported.json()["skill"]["name"], "reviewer")

            outside_root = Path(tempfile.mkdtemp())
            try:
                outside = client.post("/api/skills/import", json={"source_path": str(outside_root)})
                self.assertEqual(outside.status_code, 400)
            finally:
                if outside_root.exists():
                    for item in sorted(outside_root.rglob("*"), reverse=True):
                        if item.is_file():
                            item.unlink()
                        elif item.is_dir():
                            item.rmdir()
                    outside_root.rmdir()

            missing_skill = client.post("/api/skills/import", json={"source_path": "imports/broken"})
            self.assertEqual(missing_skill.status_code, 400)

            updated = client.put("/api/skills/writer", json={"content": "# Updated\n\nUse `search_files`.\n"})
            self.assertEqual(updated.status_code, 200)
            self.assertIn("search_files", updated.json()["skill"]["tool_dependencies"])

            readonly_update = client.put("/api/skills/plugin-review", json={"content": "# no"})
            self.assertEqual(readonly_update.status_code, 409)

            readonly_delete = client.delete("/api/skills/plugin-review")
            self.assertEqual(readonly_delete.status_code, 409)

            deleted = client.delete("/api/skills/reviewer")
            self.assertEqual(deleted.status_code, 200)
            self.assertFalse((skills_dir / "reviewer").exists())


class PluginsRouteTests(unittest.TestCase):
    def test_plugin_crud_routes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plugins_dir = root / "plugins"
            skills_dir = root / "skills"
            memory_dir = root / "memory"
            state_path = root / "state" / "plugin_state.json"
            imports_dir = root / "imports"
            plugins_dir.mkdir(parents=True, exist_ok=True)
            skills_dir.mkdir(parents=True, exist_ok=True)
            memory_dir.mkdir(parents=True, exist_ok=True)
            imports_dir.mkdir(parents=True, exist_ok=True)

            _write_plugin(
                plugins_dir,
                "demo_plugin",
                """
                name: demo-plugin
                version: 1.0.0
                description: Demo plugin
                hooks:
                  - event: FileChanged
                    message: watched
                """,
            )
            _write_plugin(
                imports_dir,
                "import_plugin",
                """
                name: imported-plugin
                version: 1.0.0
                description: Imported plugin
                """,
            )

            service = PluginService(plugins_dir, skills_dir, state_path)
            runtime = _SkillRuntime(service, memory_dir, ["read_file"])
            settings = SimpleNamespace(paths=SimpleNamespace(workspace=root))
            client = TestClient(_build_app(plugins_router, runtime=runtime, settings=settings))

            listed = client.get("/api/plugins")
            self.assertEqual(listed.status_code, 200)
            self.assertEqual(len(listed.json()["plugins"]), 1)

            detail = client.get("/api/plugins/demo-plugin")
            self.assertEqual(detail.status_code, 200)
            payload = detail.json()["plugin"]
            self.assertEqual(payload["name"], "demo-plugin")
            self.assertEqual(payload["manifest"]["version"], "1.0.0")
            self.assertEqual(payload["hook_handlers"][0]["event"], "FileChanged")

            imported = client.post("/api/plugins/import", json={"source_path": "imports/import_plugin"})
            self.assertEqual(imported.status_code, 200)
            self.assertTrue((plugins_dir / "import_plugin" / "plugin.yaml").exists())
            self.assertEqual(imported.json()["plugin"]["name"], "imported-plugin")

            updated = client.put(
                "/api/plugins/demo-plugin",
                json={
                    "content": textwrap.dedent(
                        """\
                        name: demo-plugin
                        version: 2.0.0
                        description: Demo plugin updated
                        """
                    )
                },
            )
            self.assertEqual(updated.status_code, 200)
            self.assertEqual(updated.json()["plugin"]["version"], "2.0.0")

            disabled = client.post("/api/plugins/demo-plugin/disable")
            self.assertEqual(disabled.status_code, 200)
            self.assertFalse(disabled.json()["plugin"]["enabled"])

            enabled = client.post("/api/plugins/demo-plugin/enable")
            self.assertEqual(enabled.status_code, 200)
            self.assertTrue(enabled.json()["plugin"]["enabled"])

            deleted = client.delete("/api/plugins/imported-plugin")
            self.assertEqual(deleted.status_code, 200)
            self.assertFalse((plugins_dir / "import_plugin").exists())


class ConfigRouteTests(unittest.TestCase):
    def test_project_config_can_be_read_saved_and_reloaded(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_config_project(
                root,
                """
                server:
                  port: 8005
                paths:
                  workspace: "."
                """,
            )
            home = root / "fake-home"
            home.mkdir(parents=True, exist_ok=True)

            class _ReloadRuntime:
                def __init__(self, settings):
                    self.settings = settings
                    self.scheduler_store = object()
                    self.closed = False
                    self.reload_count = 0

                def reload_ecosystem(self) -> None:
                    self.reload_count += 1

                def close(self) -> None:
                    self.closed = True

            class _ReloadScheduler:
                def __init__(self, task_store, runtime):
                    self.task_store = task_store
                    self.runtime = runtime
                    self._running = False
                    self.start_count = 0
                    self.stop_count = 0
                    self.refresh_count = 0

                async def start(self) -> None:
                    self._running = True
                    self.start_count += 1

                async def stop(self) -> None:
                    self._running = False
                    self.stop_count += 1

                def refresh_schedule(self) -> None:
                    self.refresh_count += 1

            class _ReloadChannels:
                def __init__(self, settings, runtime):
                    self.settings = settings
                    self.runtime = runtime

            with patch.dict(os.environ, {"HOME": str(home)}, clear=True):
                current_settings = reload_settings(str(root))
                previous_runtime = _ReloadRuntime(current_settings)
                previous_scheduler = _ReloadScheduler(object(), previous_runtime)
                previous_channels = _ReloadChannels(current_settings, previous_runtime)
                client = TestClient(
                    _build_app(
                        config_router,
                        runtime=previous_runtime,
                        settings=current_settings,
                        project_root=root,
                        scheduler=previous_scheduler,
                        channels=previous_channels,
                    )
                )

                with patch("backend.api.routes.config.NewmanRuntime", _ReloadRuntime), patch(
                    "backend.api.routes.config.SchedulerEngine", _ReloadScheduler
                ), patch("backend.api.routes.config.ChannelService", _ReloadChannels):
                    detail = client.get("/api/config/project")
                    self.assertEqual(detail.status_code, 200)
                    self.assertEqual(detail.json()["effective_workspace"], str(current_settings.paths.workspace))

                    updated = client.put(
                        "/api/config/project",
                        json={
                            "content": textwrap.dedent(
                                """\
                                server:
                                  port: 8010
                                paths:
                                  workspace: "workspace"
                                """
                            )
                        },
                    )
                    self.assertEqual(updated.status_code, 200)
                    self.assertTrue(updated.json()["saved"])
                    self.assertEqual(updated.json()["effective_workspace"], str((root / "workspace").resolve()))

                    reloaded = client.post("/api/config/reload")
                    self.assertEqual(reloaded.status_code, 200)
                    self.assertTrue(reloaded.json()["reloaded"])
                    self.assertEqual(reloaded.json()["effective_workspace"], str((root / "workspace").resolve()))

                self.assertEqual(previous_scheduler.stop_count, 1)
                self.assertTrue(previous_runtime.closed)
                self.assertEqual(client.app.state.settings.server.port, 8010)
                self.assertEqual(client.app.state.settings.paths.workspace, (root / "workspace").resolve())

    def test_project_config_rejects_invalid_payload(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_config_project(
                root,
                """
                server:
                  port: 8005
                """,
            )
            home = root / "fake-home"
            home.mkdir(parents=True, exist_ok=True)

            with patch.dict(os.environ, {"HOME": str(home)}, clear=True):
                settings = reload_settings(str(root))
                client = TestClient(_build_app(config_router, settings=settings, project_root=root))

                invalid = client.put("/api/config/project", json={"content": "- invalid\n- list\n"})
                self.assertEqual(invalid.status_code, 400)
                self.assertIn("顶层必须是 YAML 对象", invalid.json()["error"]["message"])


class ToolsRouteTests(unittest.TestCase):
    def test_tools_routes_return_tool_inventory(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            workspace = root / "workspace"
            workspace.mkdir(parents=True, exist_ok=True)

            class _ToolRuntime:
                def __init__(self):
                    policy = PathAccessPolicy(
                        workspace=workspace,
                        readable_roots=(workspace, Path(__file__).resolve().parents[1] / "tools"),
                        writable_roots=(workspace, Path(__file__).resolve().parents[1] / "tools"),
                        protected_roots=(),
                    )
                    self.registry = SimpleNamespace(list_tools=lambda: [ReadFileTool(policy)])
                    self.reload_count = 0

                def reload_ecosystem(self) -> None:
                    self.reload_count += 1

            runtime = _ToolRuntime()
            settings = SimpleNamespace(
                paths=SimpleNamespace(
                    workspace=workspace,
                ),
                permissions=SimpleNamespace(
                    readable_paths=[],
                    writable_paths=[Path(__file__).resolve().parents[1] / "tools"],
                    protected_paths=[],
                ),
            )
            client = TestClient(_build_app(tools_router, runtime=runtime, settings=settings))

            listed = client.get("/api/tools")
            self.assertEqual(listed.status_code, 200)
            tool = listed.json()["tools"][0]
            self.assertEqual(tool["name"], "read_file")
            self.assertEqual(tool["source_type"], "builtin")

            detail = client.get("/api/tools/read_file")
            self.assertEqual(detail.status_code, 200)
            self.assertEqual(detail.json()["tool"]["class_name"], "ReadFileTool")
            self.assertEqual(detail.json()["tool"]["approval_behavior"], "safe")
            self.assertFalse(detail.json()["tool"]["requires_approval"])

            rescanned = client.post("/api/tools/rescan")
            self.assertEqual(rescanned.status_code, 200)
            self.assertTrue(rescanned.json()["reloaded"])
            self.assertGreaterEqual(runtime.reload_count, 2)


class WorkspaceRouteTests(unittest.TestCase):
    def test_memory_workspace_returns_updated_at_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            memory_dir = Path(tmp)
            for name in ("Newman.md", "USER.md", "MEMORY.md", "SKILLS_SNAPSHOT.md"):
                (memory_dir / name).write_text(f"# {name}\n", encoding="utf-8")
            settings = SimpleNamespace(paths=SimpleNamespace(memory_dir=memory_dir, workspace=memory_dir))
            client = TestClient(_build_app(workspace_router, settings=settings))

            response = client.get("/api/workspace/memory")

            self.assertEqual(response.status_code, 200)
            payload = response.json()
            self.assertIsNotNone(payload["latest_updated_at"])
            self.assertIn("updated_at", payload["files"]["memory"])
            self.assertIn("updated_at", payload["files"]["user"])


class KnowledgeRouteTests(unittest.TestCase):
    def test_document_detail_returns_preview_markdown(self) -> None:
        document = KnowledgeDocument(
            document_id="doc-1",
            title="demo.md",
            source_path="/tmp/demo.md",
            stored_path="/tmp/stored-demo.md",
            size_bytes=128,
            content_type="text/markdown",
            parser="markdown",
            chunk_count=3,
            page_count=None,
        )
        service = SimpleNamespace(
            get_document=lambda document_id: document if document_id == "doc-1" else None,
            build_document_preview=lambda document_id: "# demo.md\n\npreview",
        )

        with patch("backend.api.routes.knowledge._service", return_value=service):
            client = TestClient(_build_app(knowledge_router, settings=SimpleNamespace()))

            response = client.get("/api/knowledge/documents/doc-1")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["document"]["document_id"], "doc-1")
        self.assertIn("preview", payload["preview_markdown"])


class SessionRouteTests(unittest.TestCase):
    def test_session_detail_returns_collaboration_mode_and_plans(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            sessions_dir = Path(tmp) / "sessions"
            session_store = SessionStore(sessions_dir)
            session = session_store.create(title="plan-session")
            session.metadata.update(
                {
                    "collaboration_mode": {
                        "mode": "plan",
                        "source": "tool",
                        "updated_at": "2026-04-22T00:00:00+00:00",
                    },
                    "plan_draft": {
                        "markdown": "# 方案\n\n- 先改后端\n- 再跑测试",
                        "status": "draft",
                        "updated_at": "2026-04-22T00:00:00+00:00",
                    },
                    "approved_plan": {
                        "markdown": "1. 先改后端\n2. 再跑测试",
                        "approved_at": "2026-04-22T00:10:00+00:00",
                    },
                }
            )
            session_store.save(session)

            runtime = SimpleNamespace(
                session_store=session_store,
                checkpoints=SimpleNamespace(get=lambda session_id: None),
                settings=AppConfig(),
                provider=_DummyContextProvider(),
            )
            client = TestClient(_build_app(sessions_router, runtime=runtime, settings=runtime.settings))

            response = client.get(f"/api/sessions/{session.session_id}")

            self.assertEqual(response.status_code, 200)
            payload = response.json()
            self.assertEqual(payload["collaboration_mode"]["mode"], "plan")
            self.assertEqual(payload["plan_draft"]["status"], "draft")
            self.assertIn("先改后端", payload["approved_plan"]["markdown"])

    def test_session_routes_can_update_mode_and_plan_draft(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            sessions_dir = Path(tmp) / "sessions"
            session_store = SessionStore(sessions_dir)
            session = session_store.create(title="manual-plan")

            runtime = SimpleNamespace(
                session_store=session_store,
                checkpoints=SimpleNamespace(get=lambda session_id: None),
                settings=AppConfig(),
                provider=_DummyContextProvider(),
            )
            client = TestClient(_build_app(sessions_router, runtime=runtime, settings=runtime.settings))

            mode_response = client.patch(
                f"/api/sessions/{session.session_id}/collaboration-mode",
                json={"mode": "plan"},
            )
            self.assertEqual(mode_response.status_code, 200)
            self.assertEqual(mode_response.json()["collaboration_mode"]["mode"], "plan")

            draft_response = client.put(
                f"/api/sessions/{session.session_id}/plan-draft",
                json={"markdown": "# Draft\n\n- 先确认需求"},
            )
            self.assertEqual(draft_response.status_code, 200)
            self.assertEqual(draft_response.json()["plan_draft"]["status"], "draft")

            get_response = client.get(f"/api/sessions/{session.session_id}/plan-draft")
            self.assertEqual(get_response.status_code, 200)
            self.assertIn("先确认需求", get_response.json()["plan_draft"]["markdown"])


class SessionEventsRouteTests(unittest.TestCase):
    def test_session_events_returns_structured_payloads_and_limit(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            audit_dir = Path(tmp)
            audit_dir.mkdir(parents=True, exist_ok=True)
            payloads = [
                {"event": "tool_call_started", "data": {"tool": "read_file"}, "request_id": "req-1", "ts": 1},
                {"event": "tool_call_finished", "data": {"tool": "read_file"}, "request_id": "req-1", "ts": 2},
                {"event": "final_response", "data": {"content": "done"}, "request_id": "req-1", "ts": 3},
            ]
            (audit_dir / "session-1.log").write_text(
                "\n".join(json.dumps(item, ensure_ascii=False) for item in payloads) + "\n",
                encoding="utf-8",
            )
            settings = SimpleNamespace(paths=SimpleNamespace(audit_dir=audit_dir))
            client = TestClient(_build_app(sessions_router, settings=settings))

            response = client.get("/api/sessions/session-1/events?limit=2")

            self.assertEqual(response.status_code, 200)
            events = response.json()["events"]
            self.assertEqual(len(events), 2)
            self.assertEqual(events[0]["event"], "tool_call_finished")
            self.assertEqual(events[1]["event"], "final_response")

    def test_session_events_handles_missing_log(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            settings = SimpleNamespace(paths=SimpleNamespace(audit_dir=Path(tmp)))
            client = TestClient(_build_app(sessions_router, settings=settings))

            response = client.get("/api/sessions/session-empty/events")

            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()["events"], [])


if __name__ == "__main__":
    unittest.main()
