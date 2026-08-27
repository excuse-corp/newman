from __future__ import annotations

import os
import tempfile
from pathlib import Path


SECRET_NAME_MARKERS = (
    "TOKEN",
    "SECRET",
    "API_KEY",
    "APIKEY",
    "PASSWORD",
    "PRIVATE_KEY",
    "CREDENTIAL",
    "ACCESS_KEY",
)

ENV_ALLOWLIST = {
    "PATH",
    "HOME",
    "LANG",
    "TMPDIR",
    "TMP",
    "TEMP",
    "NEWMAN_RUNTIME_WORKSPACE",
    "NEWMAN_PLUGIN_ROOT",
    "NEWMAN_PLUGIN_NAME",
    "NEWMAN_LARK_DEFAULT_IM_USER_ID",
    "NEWMAN_LARK_DEFAULT_IM_IDENTITY",
}


def _is_secret_name(name: str) -> bool:
    normalized = name.upper()
    return any(marker in normalized for marker in SECRET_NAME_MARKERS)


def _safe_base_env(base_env: dict[str, str] | None = None) -> dict[str, str]:
    source = os.environ if base_env is None else base_env
    env: dict[str, str] = {}
    for key, value in source.items():
        if _is_secret_name(key):
            continue
        if key in ENV_ALLOWLIST or key.startswith("LC_"):
            env[key] = value
    env.setdefault("PATH", "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin")
    return env


def ensure_runtime_dirs(skill_root: str | Path) -> dict[str, Path]:
    root = Path(skill_root).resolve()
    tmp_dir = root / ".tmp"
    pip_cache_dir = root / ".cache" / "pip"
    python_user_base = root / ".cache" / "python-user-base"
    for path in (tmp_dir, pip_cache_dir, python_user_base):
        path.mkdir(parents=True, exist_ok=True)
    return {"tmp": tmp_dir, "pip_cache": pip_cache_dir, "python_user_base": python_user_base}


def build_subprocess_env(skill_root: str | Path, base_env: dict[str, str] | None = None) -> dict[str, str]:
    env = _safe_base_env(base_env)
    runtime_dirs = ensure_runtime_dirs(skill_root)
    tmp_dir = str(runtime_dirs["tmp"])
    pip_cache_dir = str(runtime_dirs["pip_cache"])
    python_user_base = str(runtime_dirs["python_user_base"])
    env["TMPDIR"] = tmp_dir
    env["TMP"] = tmp_dir
    env["TEMP"] = tmp_dir
    env["PIP_CACHE_DIR"] = pip_cache_dir
    env["PYTHONUSERBASE"] = python_user_base
    env["PIP_DISABLE_PIP_VERSION_CHECK"] = "1"
    env["PIP_NO_INPUT"] = "1"
    return env


def configure_current_process_env(skill_root: str | Path) -> dict[str, str]:
    env = build_subprocess_env(skill_root)
    os.environ.clear()
    os.environ.update(env)
    tempfile.tempdir = env["TMPDIR"]
    return env
