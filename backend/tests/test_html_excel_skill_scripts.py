from __future__ import annotations

import importlib.util
import os
import shutil
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path
from uuid import uuid4

from openpyxl import load_workbook


REPO_ROOT = Path(__file__).resolve().parents[2]
SKILL_SCRIPTS_DIR = REPO_ROOT / "skills" / "html-excel-skill" / "scripts"


def _load_module(path: Path):
    module_name = f"test_module_{path.stem}_{uuid4().hex}"
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"failed to load module from {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _copy_scripts(skill_root: Path, names: list[str]) -> Path:
    scripts_dir = skill_root / "scripts"
    scripts_dir.mkdir(parents=True, exist_ok=True)
    for name in names:
        shutil.copy2(SKILL_SCRIPTS_DIR / name, scripts_dir / name)
    return scripts_dir


class HtmlExcelSkillScriptTests(unittest.TestCase):
    def test_runtime_support_uses_skill_local_temp_dirs(self) -> None:
        runtime_support = _load_module(SKILL_SCRIPTS_DIR / "runtime_support.py")
        tracked_keys = ("TMPDIR", "TMP", "TEMP", "PIP_CACHE_DIR")
        original_env = {key: os.environ.get(key) for key in tracked_keys}
        original_tempdir = tempfile.tempdir
        try:
            with tempfile.TemporaryDirectory() as tmp:
                skill_root = Path(tmp) / "skill"
                skill_root.mkdir()

                env = runtime_support.configure_current_process_env(skill_root)

                self.assertEqual(env["TMPDIR"], str(skill_root / ".tmp"))
                self.assertEqual(env["PIP_CACHE_DIR"], str(skill_root / ".cache" / "pip"))
                self.assertTrue((skill_root / ".tmp").is_dir())
                self.assertTrue((skill_root / ".cache" / "pip").is_dir())
                self.assertEqual(tempfile.gettempdir(), str(skill_root / ".tmp"))
        finally:
            for key, value in original_env.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value
            tempfile.tempdir = original_tempdir

    def test_run_python_uses_skill_local_runtime_env(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            skill_root = Path(tmp) / "skill"
            scripts_dir = _copy_scripts(skill_root, ["run_python.py", "runtime_support.py"])
            (skill_root / "requirements.txt").write_text("", encoding="utf-8")
            (scripts_dir / "inspect_env.py").write_text(
                textwrap.dedent(
                    """
                    import os
                    import tempfile

                    print(f"tmp={tempfile.gettempdir()}")
                    print(f"pip_cache={os.environ.get('PIP_CACHE_DIR', '')}")
                    """
                ).strip()
                + "\n",
                encoding="utf-8",
            )

            missing_tmp = skill_root / "missing-temp"
            env = os.environ.copy()
            env["TMPDIR"] = str(missing_tmp)
            env["TMP"] = str(missing_tmp)
            env["TEMP"] = str(missing_tmp)

            result = subprocess.run(
                [sys.executable, str(scripts_dir / "run_python.py"), "scripts/inspect_env.py"],
                cwd=skill_root,
                env=env,
                text=True,
                capture_output=True,
                timeout=120,
            )

            self.assertEqual(result.returncode, 0, msg=result.stderr or result.stdout)
            self.assertIn(f"tmp={skill_root / '.tmp'}", result.stdout)
            self.assertIn(f"pip_cache={skill_root / '.cache' / 'pip'}", result.stdout)
            config_text = (skill_root / ".venv" / "pyvenv.cfg").read_text(encoding="utf-8", errors="replace").casefold()
            self.assertIn("include-system-site-packages = true", config_text)

    def test_run_python_recreates_incomplete_venv(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            skill_root = Path(tmp) / "skill"
            scripts_dir = _copy_scripts(skill_root, ["run_python.py", "runtime_support.py"])
            (skill_root / "requirements.txt").write_text("", encoding="utf-8")
            (scripts_dir / "inspect_env.py").write_text("print('ok')\n", encoding="utf-8")

            venv_dir = skill_root / ".venv"
            venv_dir.mkdir()
            (venv_dir / "pyvenv.cfg").write_text(
                "include-system-site-packages = true\n",
                encoding="utf-8",
            )

            result = subprocess.run(
                [sys.executable, str(scripts_dir / "run_python.py"), "scripts/inspect_env.py"],
                cwd=skill_root,
                text=True,
                capture_output=True,
                timeout=120,
            )

            python_bin = venv_dir / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")
            self.assertEqual(result.returncode, 0, msg=result.stderr or result.stdout)
            self.assertIn("Recreating virtualenv", result.stdout)
            self.assertTrue(python_bin.exists())
            self.assertFalse(python_bin.is_symlink())

    def test_run_python_recreates_venv_from_different_python_home(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            skill_root = Path(tmp) / "skill"
            scripts_dir = _copy_scripts(skill_root, ["run_python.py", "runtime_support.py"])

            venv_dir = skill_root / ".venv"
            python_bin = venv_dir / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")
            python_bin.parent.mkdir(parents=True)
            python_bin.write_text("", encoding="utf-8")
            (venv_dir / "pyvenv.cfg").write_text(
                "home = /definitely/not/the/current/python\n"
                "include-system-site-packages = true\n",
                encoding="utf-8",
            )

            sys.path.insert(0, str(scripts_dir))
            try:
                run_python = _load_module(scripts_dir / "run_python.py")
                self.assertTrue(run_python._should_recreate_venv(venv_dir, python_bin))
            finally:
                sys.path.pop(0)

    def test_run_python_accepts_cwd_relative_script_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_root = Path(tmp)
            skill_root = tmp_root / "skill"
            scripts_dir = _copy_scripts(skill_root, ["run_python.py", "runtime_support.py"])
            (scripts_dir / "inspect_env.py").write_text("print('ok')\n", encoding="utf-8")

            original_cwd = Path.cwd()
            sys.path.insert(0, str(scripts_dir))
            try:
                os.chdir(tmp_root)
                run_python = _load_module(scripts_dir / "run_python.py")
                target = run_python._resolve_target(skill_root, "skill/scripts/inspect_env.py")
            finally:
                os.chdir(original_cwd)
                sys.path.pop(0)

            self.assertEqual(target, scripts_dir / "inspect_env.py")

    def test_html2excel_direct_invocation_recovers_without_system_tempdir(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            skill_root = Path(tmp) / "skill"
            scripts_dir = _copy_scripts(skill_root, ["html2excel.py", "runtime_support.py"])
            input_html = skill_root / "input.html"
            output_xlsx = skill_root / "output.xlsx"
            input_html.write_text(
                textwrap.dedent(
                    """
                    <!DOCTYPE html>
                    <html>
                    <body>
                      <div class="sheet-tabs">
                        <button class="tab active" data-sheet="0">Sheet1</button>
                      </div>
                      <div class="sheet" data-sheet="0" data-merges='[]' data-formulas='{}'>
                        <table>
                          <tbody>
                            <tr>
                              <td data-cell="A1" data-type="string" data-raw="hello">hello</td>
                            </tr>
                          </tbody>
                        </table>
                      </div>
                    </body>
                    </html>
                    """
                ).strip()
                + "\n",
                encoding="utf-8",
            )

            missing_tmp = skill_root / "missing-temp"
            env = os.environ.copy()
            env["TMPDIR"] = str(missing_tmp)
            env["TMP"] = str(missing_tmp)
            env["TEMP"] = str(missing_tmp)

            result = subprocess.run(
                [sys.executable, str(scripts_dir / "html2excel.py"), str(input_html), str(output_xlsx)],
                cwd=skill_root,
                env=env,
                text=True,
                capture_output=True,
                timeout=120,
            )

            self.assertEqual(result.returncode, 0, msg=result.stderr or result.stdout)
            self.assertTrue((skill_root / ".tmp").is_dir())
            self.assertTrue(output_xlsx.is_file())

            workbook = load_workbook(output_xlsx)
            try:
                self.assertEqual(workbook.active["A1"].value, "hello")
            finally:
                workbook.close()


if __name__ == "__main__":
    unittest.main()
