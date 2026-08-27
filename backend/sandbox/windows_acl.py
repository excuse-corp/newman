from __future__ import annotations

import asyncio
import hashlib
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


RUNNER_FAILURE_EXIT = 127
RUNNER_FAILURE_PREFIX = "newman-windows-acl-run:"


class WindowsAclProvider:
    """Windows WRITE_RESTRICTED token + ACL sandbox provider shell."""

    name = "windows_acl"

    def __init__(self, helper_path: str | Path | None = None, *, probe_timeout_seconds: float = 5.0):
        self.helper_path = _resolve_helper_path(helper_path)
        self.probe_timeout_seconds = probe_timeout_seconds
        self._probe_result: tuple[bool, str] | None = None

    def probe(self, policy: SandboxPolicy) -> ProviderHealth:
        if sys.platform != "win32":
            return ProviderHealth(
                available=False,
                backend=self.name,
                file_enforcement="unsupported",
                network_enforcement="unsupported",
                process_enforcement="unsupported",
                resource_enforcement="unsupported",
                detail="windows_acl is only supported on Windows",
            )
        if policy.mode == "danger-full-access":
            return ProviderHealth(
                available=False,
                backend=self.name,
                file_enforcement="unsupported",
                network_enforcement="unsupported",
                process_enforcement="unsupported",
                resource_enforcement="unsupported",
                detail="windows_acl does not accept danger-full-access",
            )
        if self.helper_path is None or not self.helper_path.exists():
            return ProviderHealth(
                available=False,
                backend=self.name,
                file_enforcement="unsupported",
                network_enforcement="unsupported",
                process_enforcement="unsupported",
                resource_enforcement="unsupported",
                detail="newman Windows ACL helper not found",
            )

        isolation_required = (policy.require_network_isolation and not policy.network_access) or policy.require_process_isolation
        if isolation_required and not policy.allow_partial_enforcement:
            return ProviderHealth(
                available=False,
                backend=self.name,
                file_enforcement="partial",
                network_enforcement="unsupported",
                process_enforcement="partial",
                process_visibility_enforcement="unsupported",
                process_lifecycle_enforcement="partial",
                resource_enforcement="partial",
                detail="windows_acl is partial; set allow_partial_enforcement=true and disable unsupported isolation requirements",
            )

        ok, detail = self._functional_probe()
        return ProviderHealth(
            available=ok,
            backend=self.name,
            file_enforcement="partial" if ok else "unsupported",
            network_enforcement="unsupported",
            process_enforcement="partial" if ok else "unsupported",
            process_visibility_enforcement="unsupported",
            process_lifecycle_enforcement="partial" if ok else "unsupported",
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
            raise SandboxUnavailableError(code, health.detail or "windows_acl unavailable")
        if self.helper_path is None:
            raise SandboxUnavailableError("SANDBOX_UNAVAILABLE", "newman Windows ACL helper not found")

        workspace = _realpath(policy.workspace_root)
        cwd = _realpath(policy.cwd)
        if not _path_is_within(cwd, workspace):
            raise SandboxUnavailableError("SANDBOX_INVALID_POLICY", f"cwd must be inside workspace for windows_acl: {cwd}")

        private_temp = Path(tempfile.mkdtemp(prefix="newman-winacl-"))
        _reject_root_conflicts(workspace, private_temp, tuple(_realpath(root) for root in policy.protected_roots))
        prepared_env, filtered_env = sanitize_environment(env, allowlist=policy.env_allowlist, workspace=workspace)
        prepared_env["TMP"] = str(private_temp)
        prepared_env["TEMP"] = str(private_temp)

        helper_argv = [
            str(self.helper_path),
            "run",
            "--workspace",
            str(workspace),
            "--temp",
            str(private_temp),
            "--mode",
            policy.mode,
        ]
        metadata = {
            "sandbox_env_filtered": filtered_env,
            "private_temp": str(private_temp),
            "windows_acl_known_boundaries": (
                "Everyone grants remain ambient",
                "NTFS hard links alias file objects",
                "network/read/process visibility isolation unsupported",
            ),
        }
        if policy.mode == "workspace-write":
            workspace_sid = workspace_write_sid(workspace)
            temp_sid = temp_write_sid(private_temp)
            helper_argv.extend(["--write-sid", workspace_sid, "--temp-write-sid", temp_sid])
            metadata["workspace_write_sid"] = workspace_sid
            metadata["temp_write_sid"] = temp_sid
        helper_argv.extend(["--", *(str(item) for item in argv)])

        async def cleanup() -> None:
            await asyncio.to_thread(shutil.rmtree, private_temp, True)

        return PreparedSandboxInvocation(
            argv=tuple(helper_argv),
            env=prepared_env,
            cwd=cwd,
            backend=self.name,
            file_enforcement="partial",
            network_enforcement="unsupported",
            process_visibility_enforcement="unsupported",
            process_lifecycle_enforcement="partial",
            resource_enforcement="partial",
            denial_signatures=("Access is denied", "access is denied", "permission denied"),
            runner_failure_rules=(
                RunnerFailureRule(
                    exit_codes=(RUNNER_FAILURE_EXIT,),
                    stderr_prefixes=(RUNNER_FAILURE_PREFIX,),
                    reason="windows ACL runner failure",
                ),
            ),
            notes=("Windows ACL WRITE_RESTRICTED partial sandbox", "network/read/process visibility isolation unsupported"),
            metadata=metadata,
            cleanup=cleanup,
        )

    def confine(self, argv: Sequence[str], policy: SandboxPolicy) -> ConfinedArgv:
        raise SandboxUnavailableError("SANDBOX_INVALID_POLICY", "windows_acl requires prepare() lifecycle")

    def _functional_probe(self) -> tuple[bool, str]:
        if self._probe_result is not None:
            return self._probe_result
        if self.helper_path is None:
            self._probe_result = (False, "newman Windows ACL helper not found")
            return self._probe_result
        try:
            with tempfile.TemporaryDirectory(prefix="newman-winacl-probe-") as tmp:
                completed = subprocess.run(
                    [
                        str(self.helper_path),
                        "run",
                        "--workspace",
                        tmp,
                        "--temp",
                        tmp,
                        "--mode",
                        "read-only",
                        "--",
                        "cmd",
                        "/c",
                        "exit",
                        "0",
                    ],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    timeout=self.probe_timeout_seconds,
                    check=False,
                )
        except (OSError, subprocess.TimeoutExpired) as exc:
            self._probe_result = (False, str(exc))
        else:
            if completed.returncode == 0:
                self._probe_result = (True, "")
            else:
                detail = (completed.stderr or completed.stdout or b"probe exited non-zero").decode("utf-8", errors="replace")
                self._probe_result = (False, detail[:500])
        return self._probe_result


def workspace_write_sid(workspace_root: str | Path) -> str:
    digest = hashlib.sha256(str(_realpath(workspace_root)).encode("utf-8")).digest()
    first = int.from_bytes(digest[0:4], "little") % (2**30 - 1) + 1
    second = int.from_bytes(digest[4:8], "little") % (2**30 - 1) + 1
    return f"S-1-4-{first}-{second}"


def temp_write_sid(temp_dir: str | Path) -> str:
    digest = hashlib.sha256(b"temp\0" + str(_realpath(temp_dir)).encode("utf-8")).digest()
    first = int.from_bytes(digest[0:4], "little") % (2**30 - 1) + 1
    second = int.from_bytes(digest[4:8], "little") % (2**30 - 1) + 1
    return f"S-1-4-{first}-{second}-1"


def _resolve_helper_path(helper_path: str | Path | None) -> Path | None:
    if helper_path:
        return Path(helper_path).expanduser().resolve(strict=False)
    resolved = shutil.which("newman-sandbox-win.exe") or shutil.which("newman-sandbox-win")
    return Path(resolved).resolve(strict=False) if resolved else None


def _reject_root_conflicts(workspace: Path, private_temp: Path, protected_roots: Sequence[Path]) -> None:
    if _path_is_within(private_temp, workspace) or _path_is_within(workspace, private_temp):
        raise SandboxUnavailableError("SANDBOX_INVALID_POLICY", "windows_acl private temp must be outside workspace")
    for protected in protected_roots:
        if _path_is_within(workspace, protected) or _path_is_within(protected, workspace):
            raise SandboxUnavailableError("SANDBOX_INVALID_POLICY", f"workspace conflicts with protected root: {protected}")
        if _path_is_within(private_temp, protected) or _path_is_within(protected, private_temp):
            raise SandboxUnavailableError("SANDBOX_INVALID_POLICY", f"private temp conflicts with protected root: {protected}")


def _realpath(path: Path | str) -> Path:
    return Path(path).expanduser().resolve(strict=False)


def _path_is_within(path: Path, root: Path) -> bool:
    try:
        Path(path).relative_to(root)
        return True
    except ValueError:
        return False
