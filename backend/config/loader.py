from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from backend.config.schema import AppConfig


CONFIG_ENV_PREFIX = "NEWMAN_"
LOGGER = logging.getLogger("newman.config")
DISPLAY_LOGGER = logging.getLogger("uvicorn.error")
SENSITIVE_MARKERS = {"api_key", "token", "secret", "password"}
_LAST_SETTINGS_REPORT: "ConfigLoadReport | None" = None
PROJECT_CONFIG_TEMPLATE = """# Newman project config
# This file is the project deployment config generated during initialization.
# backend/config/defaults.yaml provides the built-in baseline template and fallback values.
# Keep actual project settings here.
# Model settings and secrets can still be overridden through NEWMAN_* values in .env when needed.

server:
  host: "0.0.0.0"
  port: 8005

runtime:
  max_tool_depth: 30
  context_compress_threshold: 0.8
  context_critical_threshold: 0.92
  tool_retry_attempts: 3
  tool_retry_backoff_seconds: 1.0

rag:
  chroma_collection: "knowledge_chunks"
  lexical_candidate_count: 24
  vector_candidate_count: 24
  hybrid_candidate_count: 32

sandbox:
  enabled: true
  backend: "linux_bwrap"
  mode: "workspace-write"
  network_access: false
  writable_roots: []
  timeout: 30
  output_limit_bytes: 10240

approval:
  level1_blacklist:
    - "rm -rf /"
    - "sudo"
    - "su "
    - "chmod 777 /"
    - "chown root"
  level2_patterns:
    - "write_file_outside_workspace"
    - "process_spawn"
    - "terminal_mutation_or_unknown"
    - "danger_full_access_terminal"
  timeout_seconds: 120

permissions:
  readable_paths:
    - "backend"
    - "frontend"
    - "docs"
    - "backend/tests"
    - "scripts"
  writable_paths:
    - "backend_data/memory"
    - "skills"
    - "plugins"
    - "backend/tools"
  protected_paths:
    - ".env"
    - "newman.yaml"
    - "backend_data/uploads"
    - "backend_data/chroma"
    - "backend_data/sessions"
    - "backend_data/audit"

channels:
  feishu:
    enabled: true
  wecom:
    enabled: true

paths:
  workspace: "."
  data_dir: "backend_data"
  sessions_dir: "backend_data/sessions"
  memory_dir: "backend_data/memory"
  audit_dir: "backend_data/audit"
  knowledge_dir: "backend_data/knowledge"
  chroma_dir: "backend_data/chroma"
  plugins_dir: "plugins"
  skills_dir: "skills"
  mcp_dir: "backend_data/mcp"
  scheduler_dir: "backend_data/scheduler"
  channels_dir: "backend_data/channels"
"""


@dataclass
class ConfigLoadReport:
    root: str
    values: dict[str, Any]
    sources: dict[str, str]


def _read_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    loaded = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(loaded, dict):
        raise ValueError(f"Expected mapping in config file: {path}")
    return loaded


def _ensure_project_config(path: Path) -> None:
    if path.exists():
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(PROJECT_CONFIG_TEMPLATE, encoding="utf-8")
    message = f"Created missing project config template: {path}"
    LOGGER.info(message)
    if DISPLAY_LOGGER is not LOGGER:
        DISPLAY_LOGGER.info(message)


def _deep_merge(base: dict[str, Any], overlay: dict[str, Any]) -> dict[str, Any]:
    result = dict(base)
    for key, value in overlay.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def _coerce_env_value(value: str) -> Any:
    lowered = value.lower()
    if lowered in {"true", "false"}:
        return lowered == "true"
    try:
        return int(value)
    except ValueError:
        pass
    try:
        return float(value)
    except ValueError:
        pass
    return value


def _read_dotenv(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if not key:
            continue
        if value and value[0] == value[-1] and value[0] in {'"', "'"}:
            value = value[1:-1]
        values[key] = value
    return values


def _flatten_paths(data: dict[str, Any], prefix: tuple[str, ...] = ()) -> list[tuple[str, ...]]:
    items: list[tuple[str, ...]] = []
    for key, value in data.items():
        path = prefix + (str(key).lower(),)
        if isinstance(value, dict):
            items.extend(_flatten_paths(value, path))
        else:
            items.append(path)
    return items


def _assign_nested(target: dict[str, Any], path: tuple[str, ...], value: Any) -> None:
    cursor = target
    for part in path[:-1]:
        cursor = cursor.setdefault(part, {})
    cursor[path[-1]] = value


def _assign_source_map(target: dict[str, str], payload: dict[str, Any], source: str, prefix: tuple[str, ...] = ()) -> None:
    for key, value in payload.items():
        path = prefix + (str(key).lower(),)
        if isinstance(value, dict):
            _assign_source_map(target, value, source, path)
        else:
            target[".".join(path)] = source


def _flatten_leaf_values(data: dict[str, Any], prefix: tuple[str, ...] = ()) -> dict[str, Any]:
    items: dict[str, Any] = {}
    for key, value in data.items():
        path = prefix + (str(key).lower(),)
        if isinstance(value, dict):
            items.update(_flatten_leaf_values(value, path))
        else:
            items[".".join(path)] = value
    return items


def _mask_value(path: str, value: Any) -> Any:
    if any(marker in path for marker in SENSITIVE_MARKERS):
        if value in {None, ""}:
            return value
        return "***"
    return value


def _build_report(root: Path, merged: dict[str, Any], source_map: dict[str, str]) -> ConfigLoadReport:
    values = {
        path: _mask_value(path, value)
        for path, value in sorted(_flatten_leaf_values(merged).items())
    }
    sources = {path: source_map.get(path, "unknown") for path in values}
    return ConfigLoadReport(root=str(root), values=values, sources=sources)


def _log_report(report: ConfigLoadReport) -> None:
    lines = [
        "Config loaded with source trace:",
        *[
            f"  {path} = {report.values[path]!r} ({report.sources[path]})"
            for path in sorted(report.values)
        ],
    ]
    message = "\n".join(lines)
    LOGGER.info(message)
    if DISPLAY_LOGGER is not LOGGER:
        DISPLAY_LOGGER.info(message)


def _build_env_path_map(defaults: dict[str, Any]) -> dict[str, tuple[str, ...]]:
    env_map: dict[str, tuple[str, ...]] = {}
    for path in _flatten_paths(defaults):
        env_map["_".join(path)] = path
    return env_map


def _env_to_nested(defaults: dict[str, Any], dotenv_values: dict[str, str] | None = None) -> dict[str, Any]:
    env_path_map = _build_env_path_map(defaults)
    nested: dict[str, Any] = {}
    merged_env = dict(dotenv_values or {})
    merged_env.update(os.environ)
    for key, raw_value in merged_env.items():
        if not key.startswith(CONFIG_ENV_PREFIX):
            continue
        raw_path = key[len(CONFIG_ENV_PREFIX) :].lower()
        path = env_path_map.get(raw_path)
        if path is None and raw_path.startswith("provider_"):
            path = ("models", "primary", raw_path[len("provider_") :])
        if path is None and "__" in raw_path:
            path = tuple(part for part in raw_path.split("__") if part)
        if path is None:
            continue
        _assign_nested(nested, path, _coerce_env_value(raw_value))
    return nested


def _resolve_paths(config: AppConfig, project_root: Path) -> AppConfig:
    data = config.model_dump()
    paths = data["paths"]
    for name, raw_path in list(paths.items()):
        path = Path(raw_path)
        if not path.is_absolute():
            paths[name] = str((project_root / path).resolve())
    permissions = data.get("permissions", {})
    for key in ("readable_paths", "writable_paths", "protected_paths"):
        resolved: list[str] = []
        for raw_path in permissions.get(key, []):
            path = Path(raw_path)
            if not path.is_absolute():
                path = (project_root / path).resolve()
            else:
                path = path.resolve()
            resolved.append(str(path))
        permissions[key] = resolved
    return AppConfig.model_validate(data)


@lru_cache(maxsize=1)
def get_settings(project_root: str | None = None) -> AppConfig:
    global _LAST_SETTINGS_REPORT
    root = Path(project_root or Path(__file__).resolve().parents[2]).resolve()
    defaults_path = root / "backend" / "config" / "defaults.yaml"
    project_config_path = root / "newman.yaml"
    user_config_path = Path.home() / ".newman" / "config.yaml"
    project_dotenv_path = root / ".env"
    user_dotenv_path = Path.home() / ".newman" / ".env"

    defaults = _read_yaml(defaults_path)
    _ensure_project_config(project_config_path)
    project = _read_yaml(project_config_path)
    user = _read_yaml(user_config_path)
    dotenv_values = _read_dotenv(project_dotenv_path)
    dotenv_values.update(_read_dotenv(user_dotenv_path))
    merged = defaults
    source_map: dict[str, str] = {}
    _assign_source_map(source_map, defaults, "defaults.yaml")
    merged = _deep_merge(merged, project)
    _assign_source_map(source_map, project, "newman.yaml")
    merged = _deep_merge(merged, user)
    _assign_source_map(source_map, user, "~/.newman/config.yaml")
    env_values = _env_to_nested(merged, dotenv_values)
    merged = _deep_merge(merged, env_values)
    _assign_source_map(source_map, env_values, "environment")

    settings = AppConfig.model_validate_merged(merged)
    settings = _resolve_paths(settings, root)
    report = _build_report(root, settings.model_dump(mode="json"), source_map)
    _LAST_SETTINGS_REPORT = report

    for path in [
        settings.paths.data_dir,
        settings.paths.sessions_dir,
        settings.paths.memory_dir,
        settings.paths.audit_dir,
        settings.paths.knowledge_dir,
        settings.paths.chroma_dir,
        settings.paths.plugins_dir,
        settings.paths.skills_dir,
        settings.paths.mcp_dir,
        settings.paths.scheduler_dir,
        settings.paths.channels_dir,
    ]:
        path.mkdir(parents=True, exist_ok=True)

    return settings


def get_settings_report(project_root: str | None = None) -> ConfigLoadReport:
    global _LAST_SETTINGS_REPORT
    get_settings(project_root)
    if _LAST_SETTINGS_REPORT is None:
        raise RuntimeError("Settings report is unavailable")
    return _LAST_SETTINGS_REPORT


def log_settings_report(project_root: str | None = None) -> ConfigLoadReport:
    report = get_settings_report(project_root)
    _log_report(report)
    return report


def reload_settings(project_root: str | None = None) -> AppConfig:
    global _LAST_SETTINGS_REPORT
    get_settings.cache_clear()
    _LAST_SETTINGS_REPORT = None
    return get_settings(project_root)
