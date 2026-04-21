from __future__ import annotations

import importlib
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path
from types import SimpleNamespace

from backend.tools.discovery import BuiltinToolContext, load_builtin_tools
from backend.tools.workspace_fs import PathAccessPolicy


class ToolDiscoveryTests(unittest.TestCase):
    def test_load_builtin_tools_discovers_new_module(self) -> None:
        impl_dir = Path(__file__).resolve().parents[1] / "tools" / "impl"
        module_path = impl_dir / "zz_dynamic_test_tool.py"
        module_name = "backend.tools.impl.zz_dynamic_test_tool"
        module_path.write_text(
            textwrap.dedent(
                """
                from __future__ import annotations

                from typing import Any

                from backend.tools.base import BaseTool, ToolMeta
                from backend.tools.discovery import BuiltinToolContext
                from backend.tools.result import ToolExecutionResult


                class DynamicTestTool(BaseTool):
                    def __init__(self):
                        self.meta = ToolMeta(
                            name="dynamic_test_tool",
                            description="dynamic test tool",
                            input_schema={"type": "object"},
                            risk_level="low",
                            approval_behavior="safe",
                            timeout_seconds=5,
                        )

                    async def run(self, arguments: dict[str, Any], session_id: str) -> ToolExecutionResult:
                        return ToolExecutionResult(
                            success=True,
                            tool=self.meta.name,
                            action="execute",
                            summary="ok",
                        )


                def build_tools(context: BuiltinToolContext) -> list[BaseTool]:
                    return [DynamicTestTool()]
                """
            ).strip()
            + "\n",
            encoding="utf-8",
        )
        try:
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
                context = BuiltinToolContext(
                    path_policy=policy,
                    sandbox=SimpleNamespace(limits=SimpleNamespace(timeout_seconds=30), execute_shell=None),
                    knowledge_base=SimpleNamespace(),
                )

                tools = load_builtin_tools(context)

            self.assertIn("dynamic_test_tool", [tool.meta.name for tool in tools])
        finally:
            module_path.unlink(missing_ok=True)
            sys.modules.pop(module_name, None)
            importlib.invalidate_caches()


if __name__ == "__main__":
    unittest.main()
