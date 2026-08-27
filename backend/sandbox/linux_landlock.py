from __future__ import annotations

import ctypes
import errno
import os
import platform
import shutil
import sys
from pathlib import Path
from typing import Sequence

from backend.sandbox.models import ConfinedArgv, ProviderHealth, SandboxPolicy
from backend.sandbox.native_sandbox import SandboxUnavailableError


LANDLOCK_CREATE_RULESET_VERSION = 1 << 0
LANDLOCK_RULE_TYPE_PATH_BENEATH = 1
PR_SET_NO_NEW_PRIVS = 38
_SYSCALLS = {
    "x86_64": (444, 445, 446),
    "aarch64": (444, 445, 446),
    "arm64": (444, 445, 446),
    "riscv64": (444, 445, 446),
    "ppc64le": (444, 445, 446),
}

_FS_EXECUTE = 1 << 0
_FS_WRITE_FILE = 1 << 1
_FS_READ_FILE = 1 << 2
_FS_READ_DIR = 1 << 3
_FS_REMOVE_DIR = 1 << 4
_FS_REMOVE_FILE = 1 << 5
_FS_MAKE_CHAR = 1 << 6
_FS_MAKE_DIR = 1 << 7
_FS_MAKE_REG = 1 << 8
_FS_MAKE_SOCK = 1 << 9
_FS_MAKE_FIFO = 1 << 10
_FS_MAKE_BLOCK = 1 << 11
_FS_MAKE_SYM = 1 << 12
_FS_REFER = 1 << 13
_FS_TRUNCATE = 1 << 14


class _RulesetAttr(ctypes.Structure):
    _fields_ = [("handled_access_fs", ctypes.c_uint64)]


class _PathBeneathAttr(ctypes.Structure):
    _pack_ = 1
    _fields_ = [("allowed_access", ctypes.c_uint64), ("parent_fd", ctypes.c_int32)]


class LinuxLandlockProvider:
    """Landlock file provider with explicit partial-enforcement semantics."""

    name = "linux_landlock"

    def __init__(self):
        self._version: int | None = None
        self._probe_error = ""

    def probe(self, policy: SandboxPolicy) -> ProviderHealth:
        version, error = self._abi_version()
        if version is None:
            return ProviderHealth(False, self.name, "unsupported", "unsupported", "unsupported", "unsupported", error)

        partial_reason = "Landlock enforces filesystem access only; network/process isolation is unsupported"
        isolation_required = (policy.require_network_isolation and not policy.network_access) or policy.require_process_isolation
        available = not isolation_required or policy.allow_partial_enforcement
        return ProviderHealth(
            available=available,
            backend=self.name,
            file_enforcement="full",
            network_enforcement="unsupported",
            process_enforcement="unsupported",
            resource_enforcement="unsupported",
            detail="" if available else partial_reason,
        )

    def confine(self, argv: Sequence[str], policy: SandboxPolicy) -> ConfinedArgv:
        if not argv:
            raise SandboxUnavailableError("SANDBOX_INVALID_POLICY", "缺少可执行命令")
        health = self.probe(policy)
        if not health.available:
            code = (
                "SANDBOX_PARTIAL_ENFORCEMENT"
                if health.file_enforcement != "unsupported"
                else "SANDBOX_UNAVAILABLE"
            )
            raise SandboxUnavailableError(code, health.detail or "Landlock provider unavailable")
        if policy.mode == "danger-full-access":
            raise SandboxUnavailableError("SANDBOX_INVALID_POLICY", "Landlock provider 不接受 danger-full-access")
        version = self._version
        if version is None:
            raise SandboxUnavailableError("SANDBOX_UNAVAILABLE", self._probe_error or "Landlock ABI unavailable")
        preexec = self._build_preexec(policy, version, argv)
        notes = ["landlock filesystem rules applied in child preexec"]
        if health.network_enforcement == "unsupported":
            notes.append("network enforcement unsupported")
        if health.process_enforcement == "unsupported":
            notes.append("process enforcement unsupported")
        return ConfinedArgv(
            argv=tuple(str(item) for item in argv),
            backend=self.name,
            file_enforcement=health.file_enforcement,
            network_enforcement=health.network_enforcement,
            process_enforcement=health.process_enforcement,
            resource_enforcement=health.resource_enforcement,
            notes=tuple(notes),
            preexec_fn=preexec,
        )

    def _abi_version(self) -> tuple[int | None, str]:
        if self._version is not None:
            return self._version, ""
        syscalls = _SYSCALLS.get(platform.machine().lower())
        if syscalls is None or os.name != "posix" or not sys.platform.startswith("linux"):
            self._probe_error = "Landlock is only supported on known Linux architectures"
            return None, self._probe_error
        libc = ctypes.CDLL(None, use_errno=True)
        create = libc.syscall
        create.restype = ctypes.c_long
        fd = create(syscalls[0], None, 0, LANDLOCK_CREATE_RULESET_VERSION)
        if fd < 0:
            error = ctypes.get_errno()
            self._probe_error = os.strerror(error)
            return None, self._probe_error
        self._version = int(fd)
        return self._version, ""

    def _build_preexec(self, policy: SandboxPolicy, version: int, argv: Sequence[str]):
        roots = _policy_roots(policy, argv)
        traversal_roots = _traversal_roots(roots)
        allowed_read = _read_access(version)
        allowed_write = _write_access(version)
        writable = {path.resolve() for path in policy.writable_roots}
        def apply_rules() -> None:
            _restrict_self(roots, traversal_roots, writable, allowed_read, allowed_write, version)

        return apply_rules


def _policy_roots(policy: SandboxPolicy, argv: Sequence[str]) -> tuple[Path, ...]:
    if policy.mode == "workspace-write":
        for root in policy.writable_roots:
            Path(root).resolve(strict=False).mkdir(parents=True, exist_ok=True)
    roots = [policy.workspace_root, *policy.readable_roots, *policy.writable_roots]
    # A confined process still needs its interpreter and shared libraries.
    roots.extend(Path(path) for path in ("/usr", "/bin", "/lib", "/lib64") if Path(path).exists())
    executable = _resolve_executable(argv[0] if argv else "")
    if executable is not None:
        roots.extend(_executable_roots(executable))
    result: list[Path] = []
    seen: set[str] = set()
    for root in roots:
        resolved = Path(root).resolve(strict=False)
        if not resolved.exists() or str(resolved) in seen:
            continue
        seen.add(str(resolved))
        result.append(resolved)
    return tuple(result)


def _resolve_executable(raw: str) -> Path | None:
    candidate = Path(raw)
    resolved = candidate if candidate.is_absolute() else Path(shutil.which(raw) or "")
    if not str(resolved) or not resolved.exists():
        return None
    return resolved.resolve()


def _executable_roots(executable: Path) -> list[Path]:
    roots = [executable, executable.parent]
    # Virtualenv/conda interpreters commonly load libraries from a sibling lib
    # directory. Add only this interpreter prefix, never its filesystem root.
    prefix = executable.parent.parent
    sibling_lib = prefix / "lib"
    if sibling_lib.exists():
        roots.append(sibling_lib)
    return roots


def _traversal_roots(roots: Sequence[Path]) -> tuple[Path, ...]:
    result: list[Path] = []
    seen: set[str] = set()
    for root in roots:
        current = root.parent if root.is_file() else root.parent
        while current != Path("/"):
            key = str(current)
            if key not in seen:
                seen.add(key)
                result.append(current)
            current = current.parent
    return tuple(result)


def _read_access(version: int) -> int:
    value = _FS_EXECUTE | _FS_READ_FILE | _FS_READ_DIR
    return value


def _write_access(version: int) -> int:
    # The filesystem ABI exposed by the running kernel must be used as the
    # handled mask. Unknown bits make landlock_add_rule fail with EINVAL.
    value = _read_access(version) | _FS_WRITE_FILE | _FS_REMOVE_DIR | _FS_REMOVE_FILE | _FS_MAKE_DIR | _FS_MAKE_REG
    value |= _FS_MAKE_SYM | _FS_MAKE_FIFO | _FS_MAKE_SOCK | _FS_MAKE_CHAR | _FS_MAKE_BLOCK
    if version >= 2:
        value |= _FS_REFER
    if version >= 3:
        value |= _FS_TRUNCATE
    return value


def _restrict_self(
    roots: tuple[Path, ...],
    traversal_roots: tuple[Path, ...],
    writable: set[Path],
    read_access: int,
    write_access: int,
    version: int,
) -> None:
    syscalls = _SYSCALLS.get(platform.machine().lower())
    if syscalls is None:
        raise OSError("unsupported Landlock architecture")
    libc = ctypes.CDLL(None, use_errno=True)
    syscall = libc.syscall
    syscall.restype = ctypes.c_long
    if libc.prctl(PR_SET_NO_NEW_PRIVS, 1, 0, 0, 0) != 0:
        _raise_errno("prctl(PR_SET_NO_NEW_PRIVS)")
    handled = _write_access(version)
    ruleset = _RulesetAttr(handled_access_fs=handled)
    ruleset_fd = syscall(syscalls[0], ctypes.byref(ruleset), ctypes.sizeof(ruleset), 0)
    if ruleset_fd < 0:
        _raise_errno("landlock_create_ruleset")
    opened: list[int] = []
    try:
        existing = {str(root): root for root in roots}
        for root in traversal_roots:
            if root.exists() and str(root) not in existing:
                existing[str(root)] = root
                _add_path_rule(syscall, syscalls[1], ruleset_fd, root, _FS_READ_DIR)
        for root in roots:
            allowed = write_access if root in writable else read_access
            _add_path_rule(syscall, syscalls[1], ruleset_fd, root, allowed, opened)
        if syscall(syscalls[2], ruleset_fd, 0) < 0:
            _raise_errno("landlock_restrict_self")
    finally:
        for fd in opened:
            os.close(fd)
        os.close(ruleset_fd)


def _add_path_rule(syscall, add_rule_syscall: int, ruleset_fd: int, root: Path, allowed: int, opened: list[int] | None = None) -> None:
    if root.is_file():
        allowed &= ~_FS_READ_DIR
    flags = getattr(os, "O_PATH", 0) | os.O_CLOEXEC
    if root.is_dir():
        flags |= os.O_DIRECTORY
    fd = os.open(root, flags)
    if opened is not None:
        opened.append(fd)
    else:
        try:
            attr = _PathBeneathAttr(allowed_access=allowed, parent_fd=fd)
            result = syscall(add_rule_syscall, ruleset_fd, LANDLOCK_RULE_TYPE_PATH_BENEATH, ctypes.byref(attr), 0)
            if result < 0:
                _raise_errno("landlock_add_rule")
        finally:
            os.close(fd)
        return
    attr = _PathBeneathAttr(allowed_access=allowed, parent_fd=fd)
    result = syscall(add_rule_syscall, ruleset_fd, LANDLOCK_RULE_TYPE_PATH_BENEATH, ctypes.byref(attr), 0)
    if result < 0:
        _raise_errno("landlock_add_rule")


def _raise_errno(operation: str) -> None:
    error = ctypes.get_errno()
    raise OSError(error, f"{operation}: {os.strerror(error)}")
