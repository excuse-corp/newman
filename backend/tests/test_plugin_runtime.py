from __future__ import annotations

import tempfile
import textwrap
import unittest
from pathlib import Path

from backend.config.schema import ModelConfig
from backend.hooks.hook_manager import HookManager
from backend.plugin_runtime.skill_loader import SkillImportLoader, UploadedSkillFile
from backend.plugin_runtime.plugin_loader import PluginLoader
from backend.plugin_runtime.service import PluginService
from backend.providers.base import BaseProvider, ProviderChunk, ProviderResponse, TokenUsage


def _write_plugin(root: Path, name: str, manifest: str, *, skill_body: str | None = None, hook_body: str | None = None) -> None:
    plugin_dir = root / name
    plugin_dir.mkdir(parents=True, exist_ok=True)
    (plugin_dir / "plugin.yaml").write_text(textwrap.dedent(manifest).strip() + "\n", encoding="utf-8")
    if skill_body is not None:
        skill_dir = plugin_dir / "skills" / "demo_skill"
        skill_dir.mkdir(parents=True, exist_ok=True)
        (skill_dir / "SKILL.md").write_text(skill_body, encoding="utf-8")
    if hook_body is not None:
        hooks_dir = plugin_dir / "hooks"
        hooks_dir.mkdir(parents=True, exist_ok=True)
        (hooks_dir / "handler.py").write_text(hook_body, encoding="utf-8")


class PluginLoaderTests(unittest.TestCase):
    def test_invalid_plugin_collects_clear_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_plugin(
                root,
                "broken_plugin",
                """
                name: broken-plugin
                version: 1.0.0
                hooks:
                  - event: SessionStart
                    handler: hooks/missing.py
                """,
            )

            plugins, errors = PluginLoader(root).scan()

            self.assertEqual(plugins, [])
            self.assertEqual(len(errors), 1)
            self.assertEqual(errors[0].plugin_name, "broken-plugin")
            self.assertIn("Hook handler not found", errors[0].message)


class PluginServiceTests(unittest.TestCase):
    def test_service_auto_reload_detects_new_plugin(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plugins_dir = root / "plugins"
            skills_dir = root / "skills"
            state_path = root / "state" / "plugin_state.json"
            plugins_dir.mkdir(parents=True, exist_ok=True)
            skills_dir.mkdir(parents=True, exist_ok=True)
            service = PluginService(plugins_dir, skills_dir, state_path)

            self.assertEqual(service.list_plugins(), [])

            _write_plugin(
                plugins_dir,
                "demo_plugin",
                """
                name: demo-plugin
                version: 1.0.0
                description: Demo plugin
                """,
                skill_body="# Demo Skill\n\nUseful plugin skill.",
            )

            plugins = service.list_plugins()
            self.assertEqual(len(plugins), 1)
            self.assertEqual(plugins[0].name, "demo-plugin")
            self.assertEqual(service.list_skills()[0].plugin_name, "demo-plugin")

    def test_mcp_server_configs_resolve_plugin_relative_stdio_paths(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plugins_dir = root / "plugins"
            skills_dir = root / "skills"
            state_path = root / "state" / "plugin_state.json"
            plugins_dir.mkdir(parents=True, exist_ok=True)
            skills_dir.mkdir(parents=True, exist_ok=True)
            plugin_dir = plugins_dir / "tool_plugin"
            script_path = plugin_dir / "mcp" / "server.py"
            script_path.parent.mkdir(parents=True, exist_ok=True)
            script_path.write_text("print('ok')\n", encoding="utf-8")
            _write_plugin(
                plugins_dir,
                "tool_plugin",
                """
                name: tool-plugin
                version: 1.0.0
                mcp_servers:
                  - name: tool-server
                    transport: stdio
                    command:
                      - python
                    args:
                      - mcp/server.py
                """,
            )
            service = PluginService(plugins_dir, skills_dir, state_path)

            configs = service.mcp_server_configs()

            self.assertEqual(configs[0]["command"], ["python"])
            self.assertEqual(configs[0]["args"], [str(script_path.resolve())])
            self.assertEqual(configs[0]["env"]["NEWMAN_PLUGIN_ROOT"], str(plugin_dir.resolve()))
            self.assertEqual(configs[0]["env"]["NEWMAN_PLUGIN_NAME"], "tool-plugin")


class _SkillOptimizeProvider(BaseProvider):
    async def chat(self, messages, tools=None, **kwargs):
        return ProviderResponse(
            content=(
                '{"description":"Imported reporting workflow",'
                '"when_to_use":"Use for reporting tasks",'
                '"body_markdown":"# Reporting\\n\\n## Workflow\\n\\n1. Read the source material."}'
            ),
            usage=TokenUsage(input_tokens=70, output_tokens=20, total_tokens=90),
            model="test-model",
        )

    async def chat_stream(self, messages, tools=None, **kwargs):
        yield ProviderChunk(type="done", finish_reason="stop")

    def estimate_tokens(self, messages) -> int:
        return 70


class _UsageStore:
    def __init__(self) -> None:
        self.records = []

    def record(self, record) -> None:
        self.records.append(record)


class SkillImportLoaderTests(unittest.IsolatedAsyncioTestCase):
    async def test_llm_optimizer_records_usage(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            usage_store = _UsageStore()
            loader = SkillImportLoader(
                provider=_SkillOptimizeProvider(),
                provider_config=ModelConfig(type="openai_compatible", model="test-model", context_window=100000),
                usage_store=usage_store,
            )

            await loader.prepare_upload(
                [UploadedSkillFile(filename="guide.md", content=b"# Reporting\n\nMake a report.\n")],
                Path(tmp),
                requested_name="reporting",
                optimize_with_llm=True,
            )

            self.assertEqual(len(usage_store.records), 1)
            record = usage_store.records[0]
            self.assertEqual(record.request_kind, "skill_upload_optimization")
            self.assertEqual(record.total_tokens, 90)
            self.assertFalse(record.counts_toward_context_window)


class HookManagerTests(unittest.IsolatedAsyncioTestCase):
    async def test_handler_hook_executes_and_returns_message(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plugins_dir = root / "plugins"
            skills_dir = root / "skills"
            state_path = root / "state" / "plugin_state.json"
            plugins_dir.mkdir(parents=True, exist_ok=True)
            skills_dir.mkdir(parents=True, exist_ok=True)
            _write_plugin(
                plugins_dir,
                "handler_plugin",
                """
                name: handler-plugin
                version: 1.0.0
                hooks:
                  - event: FileChanged
                    handler: hooks/handler.py
                """,
                hook_body="""
from __future__ import annotations
import json
import sys

payload = json.loads(sys.stdin.read() or "{}")
print(f"hook saw {payload['context']['path']}")
""",
            )

            service = PluginService(plugins_dir, skills_dir, state_path)
            manager = HookManager(service)

            messages = await manager.handler_messages_for("FileChanged", {"path": "/tmp/demo.txt"})

            self.assertEqual(messages, ["handler-plugin: hook saw /tmp/demo.txt"])


if __name__ == "__main__":
    unittest.main()
