from __future__ import annotations

import sys
import tempfile
import types
import unittest
from pathlib import Path
from types import SimpleNamespace

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

from backend.runtime.run_loop import NewmanRuntime


class RuntimePermissionTests(unittest.TestCase):
    def test_reload_ecosystem_only_for_skills_and_plugins(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            runtime = object.__new__(NewmanRuntime)
            runtime.settings = SimpleNamespace(
                paths=SimpleNamespace(
                    skills_dir=root / "skills",
                    plugins_dir=root / "plugins",
                )
            )

            (root / "skills").mkdir(parents=True, exist_ok=True)
            (root / "plugins").mkdir(parents=True, exist_ok=True)
            (root / "workspace").mkdir(parents=True, exist_ok=True)
            tools_root = Path(__file__).resolve().parents[1] / "tools"

            self.assertTrue(runtime._should_reload_ecosystem_for_path(str(root / "skills" / "demo" / "SKILL.md")))
            self.assertTrue(runtime._should_reload_ecosystem_for_path(str(root / "plugins" / "demo" / "plugin.yaml")))
            self.assertTrue(runtime._should_reload_ecosystem_for_path(str(tools_root / "impl" / "read_file.py")))
            self.assertFalse(runtime._should_reload_ecosystem_for_path(str(root / "workspace" / "demo.txt")))

    def test_terminal_reload_checks_only_mutating_commands_on_watched_paths(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            workspace = root / "workspace"
            skills = root / "skills"
            plugins = root / "plugins"
            workspace.mkdir()
            skills.mkdir()
            plugins.mkdir()
            runtime = object.__new__(NewmanRuntime)
            runtime.settings = SimpleNamespace(
                paths=SimpleNamespace(
                    workspace=workspace,
                    skills_dir=skills,
                    plugins_dir=plugins,
                    memory_dir=root / "memory",
                ),
                permissions=SimpleNamespace(
                    readable_paths=[],
                    writable_paths=[skills, plugins, Path(__file__).resolve().parents[1] / "tools"],
                    protected_paths=[],
                ),
            )

            self.assertTrue(
                runtime._should_reload_ecosystem_for_terminal_command(
                    f"touch {skills / 'demo' / 'SKILL.md'}"
                )
            )
            self.assertFalse(
                runtime._should_reload_ecosystem_for_terminal_command(
                    f"cat {skills / 'demo' / 'SKILL.md'}"
                )
            )
            self.assertFalse(
                runtime._should_reload_ecosystem_for_terminal_command(
                    f"touch {workspace / 'note.txt'}"
                )
            )


if __name__ == "__main__":
    unittest.main()
