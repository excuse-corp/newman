from __future__ import annotations

import os
import tempfile
import textwrap
import unittest
from pathlib import Path
from unittest.mock import patch

from backend.config.loader import get_settings, get_settings_report, reload_settings


class ConfigLoaderTests(unittest.TestCase):
    def tearDown(self) -> None:
        reload_settings()

    def test_priority_and_source_trace_follow_expected_order(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._write_project(root)

            home = root / "fake-home"
            (home / ".newman").mkdir(parents=True, exist_ok=True)
            (home / ".newman" / "config.yaml").write_text(
                textwrap.dedent(
                    """
                    server:
                      port: 9200
                    models:
                      primary:
                        model: user-model
                    """
                ).strip()
                + "\n",
                encoding="utf-8",
            )
            (root / "newman.yaml").write_text(
                textwrap.dedent(
                    """
                    server:
                      port: 9100
                    models:
                      primary:
                        model: project-model
                    """
                ).strip()
                + "\n",
                encoding="utf-8",
            )
            (root / ".env").write_text("NEWMAN_SERVER_PORT=9300\n", encoding="utf-8")

            with patch.dict(os.environ, {"HOME": str(home), "NEWMAN_MODELS_PRIMARY_MODEL": "env-model"}, clear=True):
                settings = reload_settings(str(root))
                report = get_settings_report(str(root))

            self.assertEqual(settings.server.port, 9300)
            self.assertEqual(settings.models.primary.model, "env-model")
            self.assertEqual(report.sources["server.port"], "environment")
            self.assertEqual(report.sources["models.primary.model"], "environment")
            self.assertEqual(report.sources["server.host"], "defaults.yaml")

    def test_report_masks_sensitive_values(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._write_project(root)
            (root / ".env").write_text("NEWMAN_MODELS_PRIMARY_API_KEY=super-secret\n", encoding="utf-8")

            with patch.dict(os.environ, {"HOME": str(root / "fake-home")}, clear=True):
                settings = reload_settings(str(root))
                report = get_settings_report(str(root))

            self.assertEqual(settings.models.primary.api_key, "super-secret")
            self.assertEqual(report.values["models.primary.api_key"], "***")
            self.assertEqual(report.sources["models.primary.api_key"], "environment")

    def test_missing_project_config_is_created_automatically(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._write_project(root)
            project_config = root / "newman.yaml"

            self.assertFalse(project_config.exists())

            with patch.dict(os.environ, {"HOME": str(root / "fake-home")}, clear=True):
                settings = reload_settings(str(root))
                report = get_settings_report(str(root))

            self.assertTrue(project_config.exists())
            project_config_text = project_config.read_text(encoding="utf-8")
            self.assertIn("project deployment config generated during initialization", project_config_text)
            self.assertIn("server:", project_config_text)
            self.assertIn("runtime:", project_config_text)
            self.assertIn("provider_retry_attempts:", project_config_text)
            self.assertIn("sandbox:", project_config_text)
            self.assertIn("permissions:", project_config_text)
            self.assertNotIn("models:", project_config_text)
            self.assertEqual(settings.server.port, 8005)
            self.assertEqual(settings.runtime.provider_max_concurrent_requests, 1)
            self.assertEqual(settings.runtime.provider_min_interval_seconds, 0.0)
            self.assertEqual(settings.subagents.max_agents_per_run, 5)
            self.assertEqual(settings.subagents.max_parallel_agents, 5)
            self.assertEqual(report.sources["server.port"], "newman.yaml")
            self.assertEqual(report.sources["models.primary.model"], "defaults.yaml")

    def test_resolves_permission_paths_relative_to_project_root(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._write_project(root)
            (root / "newman.yaml").write_text(
                textwrap.dedent(
                    """
                    permissions:
                      readable_paths:
                        - "docs"
                      writable_paths:
                        - "skills"
                      protected_paths:
                        - ".env"
                    """
                ).strip()
                + "\n",
                encoding="utf-8",
            )

            with patch.dict(os.environ, {"HOME": str(root / "fake-home")}, clear=True):
                settings = reload_settings(str(root))

            self.assertEqual(settings.permissions.readable_paths, [root / "docs"])
            self.assertEqual(settings.permissions.writable_paths, [root / "skills"])
            self.assertEqual(settings.permissions.protected_paths, [root / ".env"])

    def test_resolves_browse_and_output_roots_relative_to_project_root(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._write_project(root)
            (root / "newman.yaml").write_text(
                textwrap.dedent(
                    """
                    paths:
                      workspace: "runtime"
                      browse_root: "."
                      output_root: "runtime/outputs/chat"
                    """
                ).strip()
                + "\n",
                encoding="utf-8",
            )

            with patch.dict(os.environ, {"HOME": str(root / "fake-home")}, clear=True):
                settings = reload_settings(str(root))

            self.assertEqual(settings.paths.workspace, root / "runtime")
            self.assertEqual(settings.paths.browse_root, root)
            self.assertEqual(settings.paths.output_root, root / "runtime" / "outputs" / "chat")

    def test_subagents_config_can_be_overridden_from_environment(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._write_project(root)

            with patch.dict(
                os.environ,
                {
                    "HOME": str(root / "fake-home"),
                    "NEWMAN_SUBAGENTS_MAX_AGENTS_PER_RUN": "2",
                    "NEWMAN_SUBAGENTS_MAX_PARALLEL_AGENTS": "1",
                    "NEWMAN_SUBAGENTS_LOCK_WAIT_TIMEOUT_SECONDS": "5",
                },
                clear=True,
            ):
                settings = reload_settings(str(root))
                report = get_settings_report(str(root))

            self.assertEqual(settings.subagents.max_agents_per_run, 2)
            self.assertEqual(settings.subagents.max_parallel_agents, 1)
            self.assertEqual(settings.subagents.lock_wait_timeout_seconds, 5)
            self.assertEqual(report.sources["subagents.max_agents_per_run"], "environment")
            self.assertEqual(report.sources["subagents.max_parallel_agents"], "environment")

    def _write_project(self, root: Path) -> None:
        config_dir = root / "backend" / "config"
        config_dir.mkdir(parents=True, exist_ok=True)
        (config_dir / "defaults.yaml").write_text(
            textwrap.dedent(
                """
                server:
                  host: "0.0.0.0"
                  port: 8005
                models:
                  primary:
                    type: "mock"
                    model: "default-model"
                    endpoint: null
                    api_key: null
                    context_window: 1000
                    embedding_dimension: null
                    timeout: 60
                    max_tokens: 512
                    temperature: 0.2
                  multimodal:
                    type: "mock"
                    model: "mm"
                    endpoint: null
                    api_key: null
                    context_window: 1000
                    embedding_dimension: null
                    timeout: 60
                    max_tokens: 512
                    temperature: 0.2
                runtime:
                  max_tool_depth: 20
                  context_compress_threshold: 0.85
                  tool_retry_attempts: 3
                  tool_retry_backoff_seconds: 1.0
                  provider_retry_attempts: 3
                  provider_retry_backoff_seconds: 1.0
                  provider_max_concurrent_requests: 1
                  provider_min_interval_seconds: 0.0
                subagents:
                  enabled: true
                  max_agents_per_run: 5
                  max_parallel_agents: 5
                  default_max_turns: 200
                  lock_wait_timeout_seconds: 30
                  sequential_context_token_limit: 2000
                sandbox:
                  enabled: true
                  backend: "linux_bwrap"
                  mode: "workspace-write"
                  network_access: false
                  writable_roots: []
                  timeout: 30
                  output_limit_bytes: 10240
                approval:
                  level1_blacklist: ["rm -rf /"]
                  level2_patterns: ["write_file_outside_workspace"]
                  timeout_seconds: 120
                channels:
                  feishu:
                    enabled: true
                    webhook_token: null
                  wecom:
                    enabled: true
                    webhook_token: null
                paths:
                  workspace: "."
                  data_dir: "backend_data"
                  sessions_dir: "backend_data/sessions"
                  memory_dir: "backend_data/memory"
                  audit_dir: "backend_data/audit"
                  subagents_dir: "backend_data/subagents"
                  plugins_dir: "plugins"
                  skills_dir: "skills"
                  mcp_dir: "backend_data/mcp"
                  scheduler_dir: "backend_data/scheduler"
                  channels_dir: "backend_data/channels"
                """
            ).strip()
            + "\n",
            encoding="utf-8",
        )


if __name__ == "__main__":
    unittest.main()
