from __future__ import annotations

import importlib
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from backend.tools.base import BaseTool

if TYPE_CHECKING:
    from backend.rag.service import KnowledgeBaseService
    from backend.sandbox.native_sandbox import NativeSandbox
    from backend.tools.workspace_fs import PathAccessPolicy


@dataclass(frozen=True)
class BuiltinToolContext:
    path_policy: "PathAccessPolicy"
    sandbox: "NativeSandbox"
    knowledge_base: "KnowledgeBaseService"


def load_builtin_tools(context: BuiltinToolContext) -> list[BaseTool]:
    importlib.invalidate_caches()
    impl_dir = Path(__file__).resolve().parent / "impl"
    tools: list[BaseTool] = []

    for module_path in sorted(impl_dir.glob("*.py")):
        if module_path.name == "__init__.py" or module_path.stem.startswith("_"):
            continue
        module_name = f"backend.tools.impl.{module_path.stem}"
        try:
            module = importlib.import_module(module_name)
            module = importlib.reload(module)
        except Exception as exc:
            print(f"[tools] failed to import {module_name}: {exc}")
            continue

        builder = getattr(module, "build_tools", None)
        if builder is None:
            continue
        try:
            built = list(builder(context))
        except Exception as exc:
            print(f"[tools] failed to build tools from {module_name}: {exc}")
            continue

        for tool in built:
            if isinstance(tool, BaseTool):
                tools.append(tool)

    return tools
