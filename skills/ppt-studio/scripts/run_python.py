from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import sys
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


def _safe_child_env(skill_root: Path) -> dict[str, str]:
    env: dict[str, str] = {}
    for key, value in os.environ.items():
        if _is_secret_name(key):
            continue
        if key in ENV_ALLOWLIST or key.startswith("LC_"):
            env[key] = value

    tmp_dir = skill_root / ".tmp"
    pip_cache_dir = skill_root / ".cache" / "pip"
    python_user_base = skill_root / ".cache" / "python-user-base"
    for path in (tmp_dir, pip_cache_dir, python_user_base):
        path.mkdir(parents=True, exist_ok=True)

    env.setdefault("PATH", "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin")
    env["TMPDIR"] = str(tmp_dir)
    env["TMP"] = str(tmp_dir)
    env["TEMP"] = str(tmp_dir)
    env["PIP_CACHE_DIR"] = str(pip_cache_dir)
    env["PYTHONUSERBASE"] = str(python_user_base)
    env["PIP_DISABLE_PIP_VERSION_CHECK"] = "1"
    env["PIP_NO_INPUT"] = "1"
    return env


def _venv_python_path(venv_dir: Path) -> Path:
    return venv_dir / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def _read_pyvenv_config(config_path: Path) -> dict[str, str]:
    config: dict[str, str] = {}
    for raw_line in config_path.read_text(encoding="utf-8", errors="replace").splitlines():
        if "=" not in raw_line:
            continue
        key, value = raw_line.split("=", 1)
        config[key.strip().casefold()] = value.strip()
    return config


def _should_recreate_venv(venv_dir: Path, python_bin: Path) -> bool:
    config_path = venv_dir / "pyvenv.cfg"
    if not config_path.is_file() or not python_bin.exists() or python_bin.is_symlink():
        return True
    home = _read_pyvenv_config(config_path).get("home")
    if not home:
        return True
    try:
        return Path(home).expanduser().resolve() != Path(sys.executable).resolve().parent
    except OSError:
        return True


def _resolve_target(skill_root: Path, raw_target: str) -> Path:
    candidate = Path(raw_target).expanduser()
    candidates = [candidate.resolve()] if candidate.is_absolute() else [
        (Path.cwd() / candidate).resolve(),
        (skill_root / candidate).resolve(),
    ]
    for resolved in candidates:
        if resolved.is_file() and resolved.is_relative_to(skill_root):
            return resolved
    raise SystemExit(f"script must be inside this skill: {raw_target}")


def _requirements_have_packages(requirements: Path) -> bool:
    if not requirements.is_file():
        return False
    for raw_line in requirements.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw_line.strip()
        if line and not line.startswith("#"):
            return True
    return False


def _requirements_hash(requirements: Path) -> str:
    if not requirements.is_file():
        return ""
    return hashlib.sha256(requirements.read_bytes()).hexdigest()


def main() -> None:
    skill_root = Path(__file__).resolve().parents[1]
    if len(sys.argv) < 2:
        raise SystemExit("usage: python scripts/run_python.py scripts/<script>.py [args...]")

    target = _resolve_target(skill_root, sys.argv[1])
    child_env = _safe_child_env(skill_root)

    venv_dir = skill_root / ".venv"
    python_bin = _venv_python_path(venv_dir)
    if venv_dir.is_dir() and _should_recreate_venv(venv_dir, python_bin):
        shutil.rmtree(venv_dir)
    if not python_bin.exists():
        subprocess.check_call(
            [sys.executable, "-m", "venv", "--copies", "--system-site-packages", str(venv_dir)],
            env=child_env,
        )

    requirements = skill_root / "requirements.txt"
    marker = venv_dir / ".req_hash"
    current_hash = _requirements_hash(requirements)
    previous_hash = marker.read_text(encoding="utf-8", errors="replace").strip() if marker.exists() else ""
    if _requirements_have_packages(requirements) and current_hash != previous_hash:
        subprocess.check_call(
            [str(python_bin), "-m", "pip", "install", "-q", "-r", str(requirements)],
            env=child_env,
        )
        marker.write_text(current_hash, encoding="utf-8")

    result = subprocess.run([str(python_bin), str(target), *sys.argv[2:]], env=child_env)
    raise SystemExit(result.returncode)


if __name__ == "__main__":
    main()
