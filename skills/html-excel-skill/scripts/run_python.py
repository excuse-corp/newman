#!/usr/bin/env python3
"""Run a Python script in a local virtualenv with the skill's requirements installed.

Usage:
    python3 run_python.py <script.py> [script_args...]

The virtualenv is created (once) under <skill_dir>/.venv and requirements.txt
is installed automatically if the venv is missing or stale.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

from runtime_support import build_subprocess_env


def _venv_python_path(venv_dir: Path) -> Path:
    if sys.platform == "win32":
        return venv_dir / "Scripts" / "python.exe"
    return venv_dir / "bin" / "python"


def _should_recreate_venv(venv_dir: Path, venv_python: Path) -> bool:
    config_path = venv_dir / "pyvenv.cfg"
    if not config_path.is_file():
        return True
    if not venv_python.exists():
        return True
    if venv_python.is_symlink():
        return True
    config = _read_pyvenv_config(config_path)
    if config.get("include-system-site-packages", "").casefold() != "true":
        return True
    home = config.get("home")
    if not home:
        return True
    try:
        return Path(home).expanduser().resolve() != Path(sys.executable).resolve().parent
    except OSError:
        return True


def _read_pyvenv_config(config_path: Path) -> dict[str, str]:
    config: dict[str, str] = {}
    for raw_line in config_path.read_text(encoding="utf-8", errors="replace").splitlines():
        if "=" not in raw_line:
            continue
        key, value = raw_line.split("=", 1)
        config[key.strip().casefold()] = value.strip()
    return config


def _resolve_target(skill_dir: Path, raw_target: str) -> Path:
    candidate = Path(raw_target).expanduser()
    candidates = [candidate.resolve()] if candidate.is_absolute() else [
        (Path.cwd() / candidate).resolve(),
        (skill_dir / candidate).resolve(),
    ]
    for resolved in candidates:
        if resolved.is_file() and resolved.is_relative_to(skill_dir):
            return resolved
    raise SystemExit(f"script must be inside this skill: {raw_target}")

def main():
    if len(sys.argv) < 2:
        print("Usage: run_python.py <script.py> [args...]", file=sys.stderr)
        sys.exit(1)

    skill_dir = Path(__file__).resolve().parents[1]
    runtime_env = build_subprocess_env(skill_dir)
    target = _resolve_target(skill_dir, sys.argv[1])

    script_args = sys.argv[2:]
    venv_dir = skill_dir / ".venv"
    venv_python = _venv_python_path(venv_dir)
    req_file = skill_dir / "requirements.txt"

    # Create venv if missing
    if venv_dir.is_dir() and _should_recreate_venv(venv_dir, venv_python):
        print(f"[run_python] Recreating virtualenv in {venv_dir} ...")
        shutil.rmtree(venv_dir)

    if not venv_dir.is_dir():
        print(f"[run_python] Creating virtualenv in {venv_dir} ...")
        subprocess.check_call(
            [sys.executable, "-m", "venv", "--copies", "--system-site-packages", str(venv_dir)],
            env=runtime_env,
        )

    # Install requirements if needed (check a marker file)
    marker = venv_dir / ".req_installed"
    req_hash_file = venv_dir / ".req_hash"

    current_hash = ""
    if req_file.is_file():
        import hashlib

        with req_file.open("rb") as f:
            current_hash = hashlib.md5(f.read()).hexdigest()

    need_install = False
    if not marker.is_file():
        need_install = True
    elif req_hash_file.is_file():
        with req_hash_file.open("r", encoding="utf-8") as f:
            if f.read().strip() != current_hash:
                need_install = True
    else:
        need_install = True

    if need_install and req_file.is_file():
        print(f"[run_python] Installing requirements from {req_file} ...")
        subprocess.check_call(
            [str(venv_python), "-m", "pip", "install", "-q", "-r", str(req_file)],
            env=runtime_env,
        )
        with req_hash_file.open("w", encoding="utf-8") as f:
            f.write(current_hash)
        # Write marker
        with marker.open("w", encoding="utf-8") as f:
            f.write("ok")
        print("[run_python] Requirements installed.")

    # Run the target script
    print(f"[run_python] Running: {target} {' '.join(script_args)}")
    result = subprocess.run([str(venv_python), str(target), *script_args], env=runtime_env)
    sys.exit(result.returncode)


if __name__ == "__main__":
    main()
