from __future__ import annotations

import os
import tempfile
from pathlib import Path


def ensure_runtime_dirs(skill_root: str | Path) -> dict[str, Path]:
    root = Path(skill_root).resolve()
    tmp_dir = root / ".tmp"
    pip_cache_dir = root / ".cache" / "pip"
    for path in (tmp_dir, pip_cache_dir):
        path.mkdir(parents=True, exist_ok=True)
    return {"tmp": tmp_dir, "pip_cache": pip_cache_dir}


def build_subprocess_env(skill_root: str | Path, base_env: dict[str, str] | None = None) -> dict[str, str]:
    env = dict(os.environ if base_env is None else base_env)
    runtime_dirs = ensure_runtime_dirs(skill_root)
    tmp_dir = str(runtime_dirs["tmp"])
    pip_cache_dir = str(runtime_dirs["pip_cache"])
    env["TMPDIR"] = tmp_dir
    env["TMP"] = tmp_dir
    env["TEMP"] = tmp_dir
    env["PIP_CACHE_DIR"] = pip_cache_dir
    return env


def configure_current_process_env(skill_root: str | Path) -> dict[str, str]:
    env = build_subprocess_env(skill_root)
    for key in ("TMPDIR", "TMP", "TEMP", "PIP_CACHE_DIR"):
        os.environ[key] = env[key]
    tempfile.tempdir = env["TMPDIR"]
    return env
