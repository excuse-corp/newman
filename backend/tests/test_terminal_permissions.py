from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from backend.config.schema import AppConfig
from backend.runtime.output_paths import turn_output_dir
from backend.sandbox.native_sandbox import NativeSandbox
from backend.sandbox.resource_limits import ResourceLimits
from backend.sandbox.linux_bwrap import build_bwrap_command
from backend.tools.impl.terminal import TerminalTool
from backend.tools.router import ToolRouter
from backend.tools.registry import ToolRegistry
from backend.tools.result import ToolExecutionResult
from backend.tools.workspace_fs import build_path_access_policy


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

    def test_terminal_static_checks_allow_writes_to_runtime_workspace(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            workspace = root / "workspace"
            workspace.mkdir()

            settings = AppConfig.model_validate({"paths": {"workspace": str(workspace)}})
            router = ToolRouter(ToolRegistry(), settings)

            reasons = router.static_checks(
                _FakeTerminalTool(),
                {"command": "touch ./notes.txt"},
            )

            self.assertEqual(reasons, [])

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


class NativeSandboxEscalationTests(unittest.IsolatedAsyncioTestCase):
    async def test_non_linux_sandbox_failure_offers_unsandboxed_retry(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            settings = AppConfig.model_validate({"paths": {"workspace": str(workspace)}})
            sandbox = NativeSandbox(
                workspace,
                ResourceLimits(timeout_seconds=1, output_limit_bytes=1024),
                settings.sandbox,
            )
            sandbox.platform = "darwin"

            result = await sandbox.execute_shell("pwd")

            self.assertFalse(result.success)
            self.assertEqual(result.category, "runtime_exception")
            self.assertTrue(result.metadata["sandbox_escalation_available"])
            self.assertEqual(result.metadata["sandbox_escalation_reason"], "sandbox_unavailable")

    async def test_permission_denied_result_is_marked_for_sandbox_escalation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            settings = AppConfig.model_validate({"paths": {"workspace": str(workspace)}})
            sandbox = NativeSandbox(
                workspace,
                ResourceLimits(timeout_seconds=1, output_limit_bytes=1024),
                settings.sandbox,
            )
            sandbox.platform = "linux"
            sandbox._bwrap_executable = "bwrap"

            async def fake_execute_bwrap(command: str, emit_output=None) -> ToolExecutionResult:
                return ToolExecutionResult(
                    success=False,
                    tool="sandbox",
                    action="execute",
                    category="runtime_exception",
                    summary="执行失败",
                    stderr="operation not permitted",
                    retryable=True,
                )

            sandbox._execute_bwrap = fake_execute_bwrap  # type: ignore[method-assign]

            result = await sandbox.execute_shell("pwd")

            self.assertFalse(result.success)
            self.assertTrue(result.metadata["sandboxed"])
            self.assertTrue(result.metadata["sandbox_escalation_available"])
            self.assertEqual(result.metadata["sandbox_escalation_reason"], "sandbox_permission_denied")


class TerminalOutputReportingTests(unittest.IsolatedAsyncioTestCase):
    async def test_terminal_reports_changed_output_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            workspace = root / "workspace"
            workspace.mkdir()
            settings = AppConfig.model_validate({"paths": {"workspace": str(workspace)}})
            policy = build_path_access_policy(settings)
            target = workspace / "report.xlsx"

            class _FakeSandbox:
                limits = SimpleNamespace(timeout_seconds=30)

                async def execute_shell(self, command: str, emit_output=None, *, force_unsandboxed: bool = False):
                    target.write_text("ok", encoding="utf-8")
                    return ToolExecutionResult(success=True, tool="sandbox", action=command, summary="执行成功")

            tool = TerminalTool(_FakeSandbox(), policy)

            result = await tool.run({"command": "python modify.py report.xlsx"}, "session-1")

            self.assertTrue(result.success)
            self.assertIn("output_files", result.metadata)
            self.assertEqual(len(result.metadata["output_files"]), 1)
            self.assertEqual(result.metadata["output_files"][0]["path"], str(target.resolve()))
            self.assertEqual(result.metadata["path"], str(target.resolve()))

    async def test_terminal_reports_outputs_directory_files_without_explicit_command_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            workspace = root / "workspace"
            workspace.mkdir()
            outputs_dir = turn_output_dir(workspace, "session-1", "turn-1")
            outputs_dir.mkdir(parents=True)
            helper_script = workspace / "modify_excel.py"
            helper_script.write_text("print('helper')", encoding="utf-8")
            target = outputs_dir / "report.xlsx"
            settings = AppConfig.model_validate({"paths": {"workspace": str(workspace)}})
            policy = build_path_access_policy(settings)

            class _FakeSandbox:
                limits = SimpleNamespace(timeout_seconds=30)

                async def execute_shell(self, command: str, emit_output=None, *, force_unsandboxed: bool = False):
                    helper_script.write_text("print('updated helper')", encoding="utf-8")
                    target.write_text("ok", encoding="utf-8")
                    return ToolExecutionResult(success=True, tool="sandbox", action=command, summary="执行成功")

            tool = TerminalTool(_FakeSandbox(), policy)

            result = await tool.run(
                {
                    "command": "python modify_excel.py",
                    "__turn_output_dir": str(outputs_dir),
                },
                "session-1",
            )

            self.assertTrue(result.success)
            self.assertIn("output_files", result.metadata)
            output_paths = {item["path"] for item in result.metadata["output_files"]}
            self.assertIn(str(target.resolve()), output_paths)
            self.assertIn(str(helper_script.resolve()), output_paths)


if __name__ == "__main__":
    unittest.main()
