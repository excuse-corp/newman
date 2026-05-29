from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from backend.config.schema import AppConfig, ModelConfig
from backend.evolution.service import EvolutionService
from backend.evolution.store import EvolutionStore
from backend.memory.checkpoint_store import CheckpointStore
from backend.memory.stable_context import StableContextLoader
from backend.plugin_runtime.service import PluginService
from backend.providers.base import BaseProvider, ProviderChunk, ProviderResponse, TokenUsage
from backend.sessions.models import SessionMessage
from backend.sessions.session_store import SessionStore
from backend.skill_runtime.registry import SkillRegistry


class _EvolutionProvider(BaseProvider):
    def __init__(self) -> None:
        self.calls: list[list[dict[str, object]]] = []

    async def chat(self, messages, tools=None, **kwargs):
        self.calls.append(messages)
        system = str(messages[0]["content"])
        user = str(messages[-1]["content"])
        if "自进化分析器" in system:
            context = _extract_payload(user)
            skill_path = context["skills"][0]["path"]
            return ProviderResponse(
                content=json.dumps(
                    {
                        "memory_updates": [
                            {
                                "text": "前端修改后应运行构建检查，并在必要时验证实际渲染。",
                                "reason": "会话中完成标准依赖构建验证。",
                                "evidence_message_ids": ["u1", "a1"],
                            }
                        ],
                        "skill_update_requests": [
                            {
                                "skill_name": context["skills"][0]["name"],
                                "skill_path": skill_path,
                                "reason": "补充前端验证流程。",
                                "desired_change": "加入构建检查脚本和完成标准。",
                            }
                        ],
                    },
                    ensure_ascii=False,
                ),
                usage=TokenUsage(input_tokens=100, output_tokens=40, total_tokens=140),
                model="test-model",
            )
        return ProviderResponse(
            content=json.dumps(
                {
                    "change_summary": "补充构建验证流程和脚本。",
                    "file_operations": [
                        {
                            "action": "update",
                            "path": "SKILL.md",
                            "content": (
                                "---\n"
                                "name: frontend-debug\n"
                                "description: Debug frontend issues\n"
                                "---\n"
                                "# Workflow\n\n"
                                "- 修改前端后运行构建检查。\n"
                            ),
                        },
                        {
                            "action": "create",
                            "path": "scripts/check_build.py",
                            "content": "def main():\n    return 'ok'\n",
                        },
                    ],
                    "validation_plan": ["parse SKILL.md", "py_compile Python scripts"],
                },
                ensure_ascii=False,
            ),
            usage=TokenUsage(input_tokens=120, output_tokens=80, total_tokens=200),
            model="test-model",
        )

    async def chat_stream(self, messages, tools=None, **kwargs):
        yield ProviderChunk(type="done", finish_reason="stop")

    def estimate_tokens(self, messages) -> int:
        return 0


def _extract_payload(content: str) -> dict:
    start = content.index("{")
    end = content.rindex("}") + 1
    return json.loads(content[start:end])


def _build_settings(root: Path) -> AppConfig:
    return AppConfig.model_validate(
        {
            "models": {
                "primary": {
                    "type": "openai_compatible",
                    "model": "test-model",
                    "context_window": 100000,
                }
            },
            "paths": {
                "workspace": str(root),
                "data_dir": str(root / "backend_data"),
                "sessions_dir": str(root / "backend_data" / "sessions"),
                "memory_dir": str(root / "backend_data" / "memory"),
                "audit_dir": str(root / "backend_data" / "audit"),
                "plugins_dir": str(root / "plugins"),
                "skills_dir": str(root / "skills"),
                "mcp_dir": str(root / "backend_data" / "mcp"),
                "scheduler_dir": str(root / "backend_data" / "scheduler"),
                "channels_dir": str(root / "backend_data" / "channels"),
                "evolution_dir": str(root / "backend_data" / "evolution"),
            },
        }
    )


def _build_service(root: Path) -> tuple[EvolutionService, SessionStore, PluginService]:
    settings = _build_settings(root)
    for path in [
        settings.paths.sessions_dir,
        settings.paths.memory_dir,
        settings.paths.plugins_dir,
        settings.paths.skills_dir,
        settings.paths.evolution_dir,
    ]:
        path.mkdir(parents=True, exist_ok=True)

    skill_dir = settings.paths.skills_dir / "frontend-debug"
    skill_dir.mkdir(parents=True, exist_ok=True)
    (skill_dir / "SKILL.md").write_text(
        "---\nname: frontend-debug\ndescription: Debug frontend issues\n---\n# Workflow\n\n- Inspect errors.\n",
        encoding="utf-8",
    )

    memory_dir = settings.paths.memory_dir
    StableContextLoader(memory_dir)
    plugin_service = PluginService(settings.paths.plugins_dir, settings.paths.skills_dir, settings.paths.data_dir / "plugin_state.json")
    skill_registry = SkillRegistry(plugin_service, memory_dir)

    def reload_ecosystem() -> None:
        plugin_service.reload()
        skill_registry.sync_snapshot()

    session_store = SessionStore(settings.paths.sessions_dir)
    service = EvolutionService(
        settings=settings,
        provider=_EvolutionProvider(),
        model_config=ModelConfig(type="openai_compatible", model="test-model", context_window=100000),
        provider_type="openai_compatible",
        session_store=session_store,
        checkpoints=CheckpointStore(settings.paths.sessions_dir),
        plugin_service=plugin_service,
        skill_registry=skill_registry,
        store=EvolutionStore(settings.paths.evolution_dir),
        reload_ecosystem=reload_ecosystem,
        usage_store=None,
    )
    return service, session_store, plugin_service


class EvolutionServiceTests(unittest.IsolatedAsyncioTestCase):
    async def test_run_updates_memory_and_skill_directory(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            service, session_store, _ = _build_service(root)
            session = session_store.create("Frontend fix")
            session_store.append_message(session.session_id, SessionMessage(id="u1", role="user", content="修一下前端页面"))
            session_store.append_message(session.session_id, SessionMessage(id="a1", role="assistant", content="已修复并通过构建。"))

            run = await service.run_for_session(session.session_id, "new_session_created")

            self.assertEqual(run.status, "applied")
            memory = (root / "backend_data" / "memory" / "MEMORY.md").read_text(encoding="utf-8")
            self.assertIn("前端修改后应运行构建检查", memory)
            skill_md = (root / "skills" / "frontend-debug" / "SKILL.md").read_text(encoding="utf-8")
            self.assertIn("修改前端后运行构建检查", skill_md)
            self.assertTrue((root / "skills" / "frontend-debug" / "scripts" / "check_build.py").exists())
            self.assertGreaterEqual(len(run.changes), 2)

    async def test_rollback_restores_changed_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            service, session_store, _ = _build_service(root)
            original_skill = (root / "skills" / "frontend-debug" / "SKILL.md").read_text(encoding="utf-8")
            original_memory = (root / "backend_data" / "memory" / "MEMORY.md").read_text(encoding="utf-8")
            session = session_store.create("Frontend fix")
            session_store.append_message(session.session_id, SessionMessage(id="u1", role="user", content="修一下前端页面"))
            session_store.append_message(session.session_id, SessionMessage(id="a1", role="assistant", content="已修复并通过构建。"))
            run = await service.run_for_session(session.session_id, "new_session_created")

            rolled_back = service.rollback_run(run.run_id)

            self.assertEqual(rolled_back.status, "rolled_back")
            self.assertEqual((root / "skills" / "frontend-debug" / "SKILL.md").read_text(encoding="utf-8"), original_skill)
            self.assertEqual((root / "backend_data" / "memory" / "MEMORY.md").read_text(encoding="utf-8"), original_memory)
            self.assertFalse((root / "skills" / "frontend-debug" / "scripts" / "check_build.py").exists())

    def test_turn_interval_uses_user_turn_count(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            service, session_store, _ = _build_service(Path(tmp))
            session = session_store.create("Long session")
            for index in range(19):
                session.messages.append(SessionMessage(id=f"u{index}", role="user", content="继续"))
            self.assertFalse(service.should_run_for_turn_interval(session))
            session.messages.append(SessionMessage(id="u19", role="user", content="继续"))
            self.assertTrue(service.should_run_for_turn_interval(session))

