from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


def main() -> None:
    skill_root = Path(__file__).resolve().parents[1]
    if len(sys.argv) < 2:
        raise SystemExit("usage: python scripts/run_python.py scripts/<script>.py [args...]")

    target = (skill_root / sys.argv[1]).resolve()
    if not target.is_file() or not target.is_relative_to(skill_root):
        raise SystemExit(f"script must be inside this skill: {sys.argv[1]}")

    venv_dir = skill_root / ".venv"
    python_bin = venv_dir / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    if not python_bin.exists():
        subprocess.check_call([sys.executable, "-m", "venv", str(venv_dir)])

    requirements = skill_root / "requirements.txt"
    if requirements.exists() and requirements.read_text(encoding="utf-8", errors="replace").strip():
        subprocess.check_call([str(python_bin), "-m", "pip", "install", "-r", str(requirements)])

    os.execv(str(python_bin), [str(python_bin), str(target), *sys.argv[2:]])


if __name__ == "__main__":
    main()
