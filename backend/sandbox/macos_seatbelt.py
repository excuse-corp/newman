from __future__ import annotations

import asyncio
import hashlib
import os
import socket
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Mapping, Sequence

from backend.sandbox.environment import sanitize_environment
from backend.sandbox.models import (
    ConfinedArgv,
    PreparedSandboxInvocation,
    ProviderHealth,
    RunnerFailureRule,
    SandboxPolicy,
)
from backend.sandbox.native_sandbox import SandboxUnavailableError


class MacOSSeatbeltProvider:
    """macOS Seatbelt provider for file write and optional network denial."""

    name = "macos_seatbelt"

    def __init__(self, seatbelt_exec: str | None = None, *, probe_timeout_seconds: float = 5.0):
        self.seatbelt_exec = seatbelt_exec or "/usr/bin/sandbox-exec"
        self.probe_timeout_seconds = probe_timeout_seconds
        self._probe_result: tuple[bool, str] | None = None

    def probe(self, policy: SandboxPolicy) -> ProviderHealth:
        if sys.platform != "darwin":
            return ProviderHealth(
                available=False,
                backend=self.name,
                file_enforcement="unsupported",
                network_enforcement="unsupported",
                process_enforcement="unsupported",
                resource_enforcement="unsupported",
                detail="macos_seatbelt is only supported on macOS",
            )
        if policy.mode == "danger-full-access":
            return ProviderHealth(
                available=False,
                backend=self.name,
                file_enforcement="unsupported",
                network_enforcement="unsupported",
                process_enforcement="unsupported",
                resource_enforcement="unsupported",
                detail="macos_seatbelt does not accept danger-full-access",
            )
        seatbelt_path = Path(self.seatbelt_exec)
        if not seatbelt_path.exists():
            return ProviderHealth(
                available=False,
                backend=self.name,
                file_enforcement="unsupported",
                network_enforcement="unsupported",
                process_enforcement="unsupported",
                resource_enforcement="unsupported",
                detail=f"sandbox-exec not found: {self.seatbelt_exec}",
            )
        if not os.access(seatbelt_path, os.X_OK):
            return ProviderHealth(
                available=False,
                backend=self.name,
                file_enforcement="unsupported",
                network_enforcement="unsupported",
                process_enforcement="unsupported",
                resource_enforcement="unsupported",
                detail=f"sandbox-exec is not executable: {self.seatbelt_exec}",
            )

        network_enforcement = "full" if not policy.network_access else "unsupported"
        process_visibility = "unsupported"
        process_lifecycle = "partial"
        process_enforcement = "partial"
        partial_required = policy.require_process_isolation
        if partial_required and not policy.allow_partial_enforcement:
            return ProviderHealth(
                available=False,
                backend=self.name,
                file_enforcement="full",
                network_enforcement=network_enforcement,
                process_enforcement=process_enforcement,
                process_visibility_enforcement=process_visibility,
                process_lifecycle_enforcement=process_lifecycle,
                resource_enforcement="partial",
                detail="macos_seatbelt has partial process enforcement; set allow_partial_enforcement=true",
            )

        ok, detail = self._functional_probe()
        return ProviderHealth(
            available=ok,
            backend=self.name,
            file_enforcement="full" if ok else "unsupported",
            network_enforcement=network_enforcement if ok else "unsupported",
            process_enforcement=process_enforcement if ok else "unsupported",
            process_visibility_enforcement=process_visibility if ok else "unsupported",
            process_lifecycle_enforcement=process_lifecycle if ok else "unsupported",
            resource_enforcement="partial" if ok else "unsupported",
            detail="" if ok else detail,
        )

    def prepare(
        self,
        argv: Sequence[str],
        policy: SandboxPolicy,
        env: Mapping[str, str] | None = None,
    ) -> PreparedSandboxInvocation:
        if not argv:
            raise SandboxUnavailableError("SANDBOX_INVALID_POLICY", "缺少可执行命令")
        health = self.probe(policy)
        if not health.available:
            code = "SANDBOX_PARTIAL_ENFORCEMENT" if health.file_enforcement != "unsupported" else "SANDBOX_UNAVAILABLE"
            raise SandboxUnavailableError(code, health.detail or "macos_seatbelt unavailable")

        workspace = _realpath(policy.workspace_root)
        cwd = _realpath(policy.cwd)
        if not _path_is_within_any(cwd, (workspace, *policy.readable_roots, *policy.writable_roots)):
            raise SandboxUnavailableError("SANDBOX_INVALID_POLICY", f"cwd 不在沙箱可见目录内: {cwd}")

        private_temp = Path(tempfile.mkdtemp(prefix="newman-seatbelt-"))
        private_temp.chmod(0o700)
        writable_roots = _writable_roots(policy, workspace, private_temp)
        protected_roots = tuple(_realpath(root) for root in policy.protected_roots)
        _reject_root_conflicts(writable_roots, protected_roots)
        profile = build_seatbelt_profile(
            writable_roots,
            protected_roots=protected_roots,
            network_access=policy.network_access,
        )
        prepared_env, filtered_env = sanitize_environment(env, allowlist=policy.env_allowlist, workspace=workspace)
        _configure_private_runtime_environment(prepared_env, private_temp)

        async def cleanup() -> None:
            await asyncio.to_thread(shutil.rmtree, private_temp, True)

        notes = [
            "macOS Seatbelt write-effect sandbox",
            "private temp/home redirected per invocation",
            "process lifecycle is process-group cleanup only",
        ]
        return PreparedSandboxInvocation(
            argv=(self.seatbelt_exec, "-p", profile, "--", *(str(item) for item in argv)),
            env=prepared_env,
            cwd=cwd,
            backend=self.name,
            file_enforcement="full",
            network_enforcement="full" if not policy.network_access else "unsupported",
            process_visibility_enforcement="unsupported",
            process_lifecycle_enforcement="partial",
            resource_enforcement="partial",
            denial_signatures=("Operation not permitted", "operation not permitted"),
            runner_failure_rules=(RunnerFailureRule(stderr_prefixes=("sandbox-exec: ",), reason="seatbelt runner failure"),),
            notes=tuple(notes),
            metadata={
                "sandbox_env_filtered": filtered_env,
                "private_temp": str(private_temp),
                "private_home": prepared_env.get("HOME", ""),
                "seatbelt_exec": str(_realpath(self.seatbelt_exec)),
                "seatbelt_profile_sha256": hashlib.sha256(profile.encode("utf-8")).hexdigest(),
                "seatbelt_profile_bytes": len(profile.encode("utf-8")),
                "seatbelt_writable_roots": len(writable_roots),
                "seatbelt_protected_roots": len(protected_roots),
                "seatbelt_model": "allow-default/write-deny-with-explicit-write-grants",
            },
            cleanup=cleanup,
            start_new_session=True,
        )

    def confine(self, argv: Sequence[str], policy: SandboxPolicy) -> ConfinedArgv:
        raise SandboxUnavailableError("SANDBOX_INVALID_POLICY", "macos_seatbelt requires prepare() lifecycle")

    def _functional_probe(self) -> tuple[bool, str]:
        if self._probe_result is not None:
            return self._probe_result
        try:
            self._probe_result = self._run_functional_probe()
        except (OSError, subprocess.TimeoutExpired, RuntimeError) as exc:
            self._probe_result = (False, str(exc))
        return self._probe_result

    def _run_functional_probe(self) -> tuple[bool, str]:
        with tempfile.TemporaryDirectory(prefix="newman-seatbelt-probe-") as tmp:
            root = Path(tmp).resolve()
            workspace = root / "workspace"
            private_temp = root / "private-temp"
            workspace.mkdir()
            private_temp.mkdir()
            protected = workspace / "protected.env"
            protected.write_text("secret", encoding="utf-8")
            outside = root / "outside.txt"

            write_profile = build_seatbelt_profile(
                (workspace, private_temp),
                protected_roots=(protected,),
                network_access=False,
            )
            read_only_profile = build_seatbelt_profile(
                (private_temp,),
                protected_roots=(protected,),
                network_access=False,
            )

            checks = [
                ("true under profile", write_profile, "pass", "import sys; sys.exit(0)"),
                (
                    "workspace write",
                    write_profile,
                    "pass",
                    f"from pathlib import Path; Path({str(workspace / 'ok.txt')!r}).write_text('ok', encoding='utf-8')",
                ),
                (
                    "private temp write",
                    write_profile,
                    "pass",
                    f"from pathlib import Path; Path({str(private_temp / 'scratch.txt')!r}).write_text('ok', encoding='utf-8')",
                ),
                (
                    "outside write denied",
                    write_profile,
                    "fail",
                    f"from pathlib import Path; Path({str(outside)!r}).write_text('no', encoding='utf-8')",
                ),
                (
                    "protected write denied",
                    write_profile,
                    "fail",
                    f"from pathlib import Path; Path({str(protected)!r}).write_text('changed', encoding='utf-8')",
                ),
                (
                    "read-only workspace write denied",
                    read_only_profile,
                    "fail",
                    f"from pathlib import Path; Path({str(workspace / 'readonly.txt')!r}).write_text('no', encoding='utf-8')",
                ),
                (
                    "read-only private temp write",
                    read_only_profile,
                    "pass",
                    f"from pathlib import Path; Path({str(private_temp / 'readonly-scratch.txt')!r}).write_text('ok', encoding='utf-8')",
                ),
            ]
            symlink = workspace / "escape-link.txt"
            symlink.symlink_to(outside)
            checks.append(
                (
                    "symlink escape write denied",
                    write_profile,
                    "fail",
                    f"from pathlib import Path; Path({str(symlink)!r}).write_text('no', encoding='utf-8')",
                )
            )
            for label, profile, expectation, script in checks:
                completed = self._run_python_probe(profile, script, cwd=workspace, private_temp=private_temp)
                if expectation == "pass" and completed.returncode != 0:
                    return False, _probe_detail(label, completed)
                if expectation == "fail" and completed.returncode == 0:
                    return False, f"{label} unexpectedly succeeded"
            if protected.read_text(encoding="utf-8") != "secret":
                return False, "protected file changed during probe"
            if outside.exists():
                return False, "outside file changed during probe"

            network = self._probe_network_denial(write_profile, workspace, private_temp)
            if network is not None:
                return network
        return True, ""

    def _run_python_probe(
        self,
        profile: str,
        script: str,
        *,
        cwd: Path,
        private_temp: Path,
    ) -> subprocess.CompletedProcess[bytes]:
        env = dict(os.environ)
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        env["TMPDIR"] = str(private_temp)
        env["TMP"] = str(private_temp)
        env["TEMP"] = str(private_temp)
        return subprocess.run(
            [self.seatbelt_exec, "-p", profile, "--", sys.executable, "-c", script],
            cwd=str(cwd),
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=self.probe_timeout_seconds,
            check=False,
        )

    def _probe_network_denial(self, profile: str, cwd: Path, private_temp: Path) -> tuple[bool, str] | None:
        listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            listener.bind(("127.0.0.1", 0))
            listener.listen(1)
            port = listener.getsockname()[1]
            script = (
                "import socket; "
                "s=socket.socket(); "
                "s.settimeout(1); "
                f"s.connect(('127.0.0.1', {port}))"
            )
            completed = self._run_python_probe(profile, script, cwd=cwd, private_temp=private_temp)
            if completed.returncode == 0:
                return False, "network deny probe unexpectedly connected to localhost"
            return None
        finally:
            listener.close()


def build_seatbelt_profile(
    writable_roots: Sequence[Path],
    *,
    protected_roots: Sequence[Path] = (),
    network_access: bool,
) -> str:
    forms = [
        "(version 1)",
        "(allow default)",
        "(deny file-write*)",
        f"(allow file-write* (literal {_sbpl_string('/dev/null')}))",
    ]
    roots = _dedupe_paths(_realpath(root) for root in writable_roots)
    if roots:
        grants = " ".join(_path_filter(root) for root in roots)
        forms.append(f"(allow file-write* {grants})")
    protected = _dedupe_paths(_realpath(root) for root in protected_roots)
    if protected:
        denies = " ".join(_path_filter(root) for root in protected)
        forms.append(f"(deny file-write* {denies})")
    if not network_access:
        forms.append("(deny network*)")
    return " ".join(forms)


def _path_filter(path: Path) -> str:
    quoted = _sbpl_string(str(path))
    return f"(literal {quoted}) (subpath {quoted})"


def _sbpl_string(value: str) -> str:
    if "\x00" in value:
        raise ValueError("SBPL string cannot contain NUL")
    escaped = value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")
    return f'"{escaped}"'


def _writable_roots(policy: SandboxPolicy, workspace: Path, private_temp: Path) -> tuple[Path, ...]:
    roots: list[Path] = [private_temp]
    if policy.mode == "workspace-write":
        roots.append(workspace)
        roots.extend(_realpath(root) for root in policy.writable_roots)
    return tuple(_dedupe_paths(roots))


def _configure_private_runtime_environment(env: dict[str, str], private_temp: Path) -> None:
    private_home = private_temp / "home"
    private_cache = private_temp / "cache"
    private_config = private_temp / "config"
    private_data = private_temp / "data"
    private_pycache = private_temp / "pycache"
    for path in (private_home, private_cache, private_config, private_data, private_pycache):
        path.mkdir(mode=0o700, parents=True, exist_ok=True)
    env["HOME"] = str(private_home)
    env["TMPDIR"] = str(private_temp)
    env["TMP"] = str(private_temp)
    env["TEMP"] = str(private_temp)
    env["XDG_CACHE_HOME"] = str(private_cache)
    env["XDG_CONFIG_HOME"] = str(private_config)
    env["XDG_DATA_HOME"] = str(private_data)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["PYTHONPYCACHEPREFIX"] = str(private_pycache)


def _reject_root_conflicts(writable_roots: Sequence[Path], protected_roots: Sequence[Path]) -> None:
    for writable in writable_roots:
        for protected in protected_roots:
            if _path_is_within(writable, protected):
                raise SandboxUnavailableError(
                    "SANDBOX_INVALID_POLICY",
                    f"writable root is inside protected root: {writable} / {protected}",
                )


def _probe_detail(label: str, completed: subprocess.CompletedProcess[bytes]) -> str:
    output = (completed.stderr or completed.stdout or b"").decode("utf-8", errors="replace").strip()
    return f"{label} failed with exit {completed.returncode}: {output[:500]}"


def _realpath(path: Path | str) -> Path:
    return Path(path).expanduser().resolve(strict=False)


def _dedupe_paths(paths) -> list[Path]:
    result: list[Path] = []
    seen: set[str] = set()
    for path in paths:
        resolved = _realpath(path)
        key = str(resolved)
        if key in seen:
            continue
        seen.add(key)
        result.append(resolved)
    return result


def _path_is_within_any(path: Path, roots: Sequence[Path]) -> bool:
    return any(_path_is_within(path, _realpath(root)) for root in roots)


def _path_is_within(path: Path, root: Path) -> bool:
    try:
        Path(path).relative_to(root)
        return True
    except ValueError:
        return Path(path) == root
