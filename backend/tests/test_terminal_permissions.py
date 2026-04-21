from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from backend.config.schema import AppConfig
from backend.sandbox.linux_bwrap import build_bwrap_command
from backend.tools.router import ToolRouter
from backend.tools.registry import ToolRegistry


class _FakeTerminalTool:
    def __init__(self) -> None:
        self.meta = SimpleNamespace(name="terminal")


class _FakeWriteFileTool:
    def __init__(self) -> None:
        self.meta = SimpleNamespace(name="write_file")


class _FakeMCPTool:
    def __init__(self) -> None:
        self.meta = SimpleNamespace(name="mcp__demo__fs_reader")


class TerminalPermissionTests(unittest.TestCase):
    def test_terminal_static_checks_deny_protected_reads(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            workspace = root / "workspace"
            protected_file = root / ".env"
            workspace.mkdir()
            protected_file.write_text("SECRET=1\n", encoding="utf-8")

            settings = AppConfig.model_validate(
                {
                    "paths": {"workspace": str(workspace)},
                    "permissions": {"protected_paths": [str(protected_file)]},
                }
            )
            router = ToolRouter(ToolRegistry(), settings)

            reasons = router.static_checks(_FakeTerminalTool(), {"command": f"cat {protected_file}"})

            self.assertEqual(len(reasons), 1)
            self.assertTrue(reasons[0].startswith("terminal_read_protected_path:"))

    def test_terminal_static_checks_deny_writes_to_readonly_roots(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            workspace = root / "workspace"
            readonly_root = root / "backend"
            workspace.mkdir()
            readonly_root.mkdir()

            settings = AppConfig.model_validate(
                {
                    "paths": {"workspace": str(workspace)},
                    "permissions": {"readable_paths": [str(readonly_root)]},
                }
            )
            router = ToolRouter(ToolRegistry(), settings)

            reasons = router.static_checks(
                _FakeTerminalTool(),
                {"command": f"echo hi > {readonly_root / 'app.py'}"},
            )

            self.assertEqual(len(reasons), 1)
            self.assertTrue(reasons[0].startswith("terminal_write_readonly_path:"))

    def test_terminal_static_checks_deny_writes_outside_allowed_paths(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            workspace = root / "workspace"
            outside = root / "outside"
            workspace.mkdir()
            outside.mkdir()

            settings = AppConfig.model_validate({"paths": {"workspace": str(workspace)}})
            router = ToolRouter(ToolRegistry(), settings)

            reasons = router.static_checks(_FakeTerminalTool(), {"command": f"touch {outside / 'demo.txt'}"})

            self.assertEqual(len(reasons), 1)
            self.assertTrue(reasons[0].startswith("terminal_write_outside_writable_paths:"))

    def test_write_file_static_checks_tag_skill_maintenance(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            workspace = root / "workspace"
            skills = root / "skills"
            workspace.mkdir()
            skills.mkdir()

            settings = AppConfig.model_validate(
                {
                    "paths": {
                        "workspace": str(workspace),
                        "skills_dir": str(skills),
                    },
                    "permissions": {"writable_paths": [str(skills)]},
                }
            )
            router = ToolRouter(ToolRegistry(), settings)

            reasons = router.static_checks(
                _FakeWriteFileTool(),
                {"path": str(skills / "demo" / "SKILL.md")},
            )

            self.assertIn("maintain_skill", reasons)

    def test_terminal_static_checks_tag_plugin_maintenance(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            workspace = root / "workspace"
            plugins = root / "plugins"
            workspace.mkdir()
            plugins.mkdir()

            settings = AppConfig.model_validate(
                {
                    "paths": {
                        "workspace": str(workspace),
                        "plugins_dir": str(plugins),
                    },
                    "permissions": {"writable_paths": [str(plugins)]},
                }
            )
            router = ToolRouter(ToolRegistry(), settings)

            reasons = router.static_checks(
                _FakeTerminalTool(),
                {"command": f"touch {plugins / 'demo' / 'plugin.yaml'}"},
            )

            self.assertIn("maintain_plugin", reasons)

    def test_mcp_static_checks_deny_paths_outside_workspace(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            workspace = root / "workspace"
            outside = root / "outside"
            workspace.mkdir()
            outside.mkdir()

            settings = AppConfig.model_validate({"paths": {"workspace": str(workspace)}})
            router = ToolRouter(ToolRegistry(), settings)

            reasons = router.static_checks(
                _FakeMCPTool(),
                {"path": str(outside / "demo.txt")},
            )

            self.assertEqual(len(reasons), 1)
            self.assertTrue(reasons[0].startswith("mcp_path_outside_workspace:"))

    def test_mcp_static_checks_deny_protected_workspace_paths(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            workspace = root / "workspace"
            protected_file = workspace / ".env"
            workspace.mkdir()
            protected_file.write_text("SECRET=1\n", encoding="utf-8")

            settings = AppConfig.model_validate(
                {
                    "paths": {"workspace": str(workspace)},
                    "permissions": {"protected_paths": [str(protected_file)]},
                }
            )
            router = ToolRouter(ToolRegistry(), settings)

            reasons = router.static_checks(
                _FakeMCPTool(),
                {"outputFile": str(protected_file)},
            )

            self.assertEqual(len(reasons), 1)
            self.assertTrue(reasons[0].startswith("mcp_path_protected:"))

    def test_bwrap_command_mounts_readable_writable_and_protected_paths(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            workspace = root / "workspace"
            readable = root / "backend"
            writable = root / "skills"
            protected_dir = root / "uploads"
            protected_file = root / ".env"
            for path in (workspace, readable, writable, protected_dir):
                path.mkdir(parents=True, exist_ok=True)
            protected_file.write_text("SECRET=1\n", encoding="utf-8")

            argv = build_bwrap_command(
                bwrap_executable="bwrap",
                workspace=workspace,
                readable_roots=[workspace, readable, writable],
                writable_roots=[workspace, writable],
                protected_roots=[protected_dir, protected_file],
                mode="workspace-write",
                network_access=False,
                command="pwd",
            )

            self.assertIn("--ro-bind", argv)
            self.assertIn(str(readable), argv)
            self.assertIn("--bind", argv)
            self.assertIn(str(writable), argv)
            self.assertIn("--tmpfs", argv)
            self.assertIn(str(protected_dir), argv)
            self.assertIn("/dev/null", argv)
            self.assertIn(str(protected_file), argv)


if __name__ == "__main__":
    unittest.main()
