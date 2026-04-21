from __future__ import annotations

import base64
import json
import tempfile
import unittest
from pathlib import Path

from backend.tools.impl.edit_file import EditFileTool
from backend.tools.impl.read_file import ReadFileTool
from backend.tools.impl.write_file import WriteFileTool
from backend.tools.workspace_fs import PathAccessPolicy


class PathPermissionToolTests(unittest.IsolatedAsyncioTestCase):
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
