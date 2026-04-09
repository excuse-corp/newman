from __future__ import annotations

import json
import tempfile
import textwrap
import unittest
from pathlib import Path
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.api.middleware.error_handler import install_error_handlers
from backend.api.routes.approvals import router as approvals_router
from backend.api.routes.messages import router as messages_router
from backend.api.routes.sessions import router as sessions_router
from backend.api.routes.skills import router as skills_router
from backend.api.routes.workspace import router as workspace_router
from backend.plugin_runtime.service import PluginService
from backend.skill_runtime.registry import SkillRegistry
from backend.tools.approval import ApprovalManager, ApprovalRequest


class _DummySessionStore:
    def get(self, session_id: str) -> dict:
        return {"session_id": session_id}


class _DummyMultimodalAnalyzer:
    async def analyze_images(self, content: str, paths: list[Path]) -> list[dict]:
        return [{"summary": f"image:{path.name}"} for path in paths]


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
    ) -> None:
        self.calls.append(
            {
                "session_id": session_id,
                "content": content,
                "user_metadata": user_metadata,
                "turn_approval_mode": turn_approval_mode,
            }
        )
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


class _SkillRuntime:
    def __init__(self, plugin_service: PluginService, memory_dir: Path, tool_names: list[str]):
        self.plugin_service = plugin_service
        self.skill_registry = SkillRegistry(plugin_service, memory_dir)
        self.registry = _DummyRegistry(tool_names)

    def reload_ecosystem(self) -> None:
        self.plugin_service.reload()
        self.skill_registry.sync_snapshot()


def _build_app(router, *, runtime=None, settings=None) -> FastAPI:
    app = FastAPI()
    app.state.runtime = runtime or SimpleNamespace()
    app.state.settings = settings or SimpleNamespace()
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


class MessageRouteTests(unittest.TestCase):
    def test_messages_json_parses_approval_mode(self) -> None:
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
            self.assertEqual(runtime.calls[0]["turn_approval_mode"], "auto_approve_level2")
            self.assertEqual(runtime.calls[0]["user_metadata"]["approval_mode"], "auto_approve_level2")

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


class ApprovalRouteTests(unittest.TestCase):
    def test_approve_and_reject_contracts(self) -> None:
        approvals = ApprovalManager()
        request = ApprovalRequest(
            approval_request_id="apr-1",
            session_id="session-1",
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
