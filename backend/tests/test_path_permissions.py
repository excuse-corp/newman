from __future__ import annotations

import base64
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from backend.tools.impl.edit_file import EditFileTool
from backend.tools.impl.read_file import ReadFileTool
from backend.tools.impl.write_file import WriteFileTool
from backend.tools.workspace_fs import PathAccessPolicy, build_path_access_policy


class PathPermissionToolTests(unittest.IsolatedAsyncioTestCase):
    async def test_build_path_access_policy_treats_workspace_as_writable_operation_space(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            workspace = root / "workspace"
            writable = workspace / "skills"
            workspace.mkdir()
            writable.mkdir()
            settings = SimpleNamespace(
                paths=SimpleNamespace(workspace=workspace),
                permissions=SimpleNamespace(
                    readable_paths=[],
                    writable_paths=[writable],
                    protected_paths=[],
                ),
            )

            policy = build_path_access_policy(settings)

            self.assertIn(workspace.resolve(), policy.readable_roots)
            self.assertIn(workspace.resolve(), policy.writable_roots)
            self.assertIn(writable.resolve(), policy.writable_roots)

            result = await WriteFileTool(policy).run({"path": "outputs/result.html", "content": "<html></html>"}, "session-0")

            self.assertTrue(result.success)
            self.assertTrue((workspace / "outputs" / "result.html").exists())

    async def test_read_file_can_read_from_additional_readable_root(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            workspace = root / "workspace"
            shared = root / "shared"
            workspace.mkdir()
            shared.mkdir()
            target = shared / "guide.md"
            target.write_text("hello\nworld\n", encoding="utf-8")

            policy = PathAccessPolicy(
                workspace=workspace,
                readable_roots=(workspace, shared),
                writable_roots=(workspace,),
                protected_roots=(),
            )

            result = await ReadFileTool(policy).run({"path": str(target)}, "session-1")

            self.assertTrue(result.success)
            payload = json.loads(result.stdout)
            self.assertEqual(base64.b64decode(payload["dataBase64"]).decode("utf-8"), "hello\nworld\n")

    async def test_runtime_logs_can_be_read_without_exposing_audit_or_sessions(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            workspace = root / "workspace"
            logs = root / "backend_data" / "run" / "logs"
            audit = root / "backend_data" / "audit"
            sessions = root / "backend_data" / "sessions"
            for path in (workspace, logs, audit, sessions):
                path.mkdir(parents=True)
            backend_log = logs / "backend.log"
            audit_log = audit / "session-1.log"
            session_json = sessions / "session-1.json"
            backend_log.write_text("backend ready\n", encoding="utf-8")
            audit_log.write_text("private audit\n", encoding="utf-8")
            session_json.write_text("{}", encoding="utf-8")

            settings = SimpleNamespace(
                paths=SimpleNamespace(workspace=workspace),
                permissions=SimpleNamespace(
                    readable_paths=[logs],
                    writable_paths=[],
                    protected_paths=[audit, sessions],
                ),
            )
            policy = build_path_access_policy(settings)

            result = await ReadFileTool(policy).run({"path": str(backend_log)}, "session-logs")
            self.assertTrue(result.success)
            payload = json.loads(result.stdout)
            self.assertEqual(base64.b64decode(payload["dataBase64"]).decode("utf-8"), "backend ready\n")

            audit_result = await ReadFileTool(policy).run({"path": str(audit_log)}, "session-logs")
            self.assertFalse(audit_result.success)
            self.assertEqual(audit_result.category, "permission_error")
            self.assertEqual(audit_result.summary, "path 位于受保护目录内")

            session_result = await ReadFileTool(policy).run({"path": str(session_json)}, "session-logs")
            self.assertFalse(session_result.success)
            self.assertEqual(session_result.category, "permission_error")
            self.assertEqual(session_result.summary, "path 位于受保护目录内")

    async def test_write_file_rejects_read_only_root(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            workspace = root / "workspace"
            readonly = root / "readonly"
            workspace.mkdir()
            readonly.mkdir()

            policy = PathAccessPolicy(
                workspace=workspace,
                readable_roots=(workspace, readonly),
                writable_roots=(workspace,),
                protected_roots=(),
            )

            result = await WriteFileTool(policy).run(
                {"path": str(readonly / "blocked.txt"), "content": "hello"},
                "session-2",
            )

            self.assertFalse(result.success)
            self.assertEqual(result.category, "permission_error")
            self.assertEqual(result.summary, "path 不在允许写入的目录内")

    async def test_write_file_requires_content_argument(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            workspace = root / "workspace"
            workspace.mkdir()

            policy = PathAccessPolicy(
                workspace=workspace,
                readable_roots=(workspace,),
                writable_roots=(workspace,),
                protected_roots=(),
            )

            result = await WriteFileTool(policy).run({"path": "missing.txt"}, "session-4")

            self.assertFalse(result.success)
            self.assertEqual(result.category, "validation_error")
            self.assertEqual(result.summary, "缺少必填参数: content")
            self.assertFalse((workspace / "missing.txt").exists())

    async def test_write_file_streams_html_content_before_completion(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            workspace = root / "workspace"
            workspace.mkdir()

            policy = PathAccessPolicy(
                workspace=workspace,
                readable_roots=(workspace,),
                writable_roots=(workspace,),
                protected_roots=(),
            )
            chunks: list[tuple[str, str]] = []

            async def emit_output(stream: str, delta: str) -> None:
                chunks.append((stream, delta))

            content = "<!doctype html><html><body><h1>Demo</h1></body></html>"
            result = await WriteFileTool(policy).run_streaming(
                {"path": "diagram.html", "content": content},
                "session-5",
                emit_output=emit_output,
            )

            self.assertTrue(result.success)
            self.assertEqual((workspace / "diagram.html").read_text(encoding="utf-8"), content)
            self.assertEqual("".join(delta for _stream, delta in chunks), content)
            self.assertTrue(all(stream == "file_content" for stream, _delta in chunks))

    async def test_edit_file_can_update_additional_writable_root(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            workspace = root / "workspace"
            managed = root / "managed"
            workspace.mkdir()
            managed.mkdir()
            target = managed / "plugin.py"
            target.write_text("print('old')\n", encoding="utf-8")

            policy = PathAccessPolicy(
                workspace=workspace,
                readable_roots=(workspace, managed),
                writable_roots=(workspace, managed),
                protected_roots=(),
            )

            result = await EditFileTool(policy).run(
                {"path": str(target), "edits": [{"old_text": "old", "new_text": "new"}]},
                "session-3",
            )

            self.assertTrue(result.success)
            self.assertIn("共应用 1 处替换", result.summary)
            self.assertEqual(target.read_text(encoding="utf-8"), "print('new')\n")


if __name__ == "__main__":
    unittest.main()
