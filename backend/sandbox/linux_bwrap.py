from __future__ import annotations

import os
from pathlib import Path
from shutil import which


FIXED_READ_ROOTS = [
    Path("/usr"),
    Path("/usr/local"),
    Path("/bin"),
    Path("/lib"),
    Path("/lib64"),
]
NETWORK_READ_MOUNTS = [
    (Path("/etc/resolv.conf"), Path("/etc/resolv.conf")),
    (Path("/etc/nsswitch.conf"), Path("/etc/nsswitch.conf")),
    (Path("/etc/hosts"), Path("/etc/hosts")),
    (Path("/etc/ssl"), Path("/etc/ssl")),
    (Path("/etc/pki"), Path("/etc/pki")),
]


def resolve_bwrap_executable() -> str | None:
    return which("bwrap")


def build_bwrap_command(
    *,
    bwrap_executable: str,
    workspace: Path,
    readable_roots: list[Path],
    writable_roots: list[Path],
    protected_roots: list[Path],
    mode: str,
    network_access: bool,
    command: str,
) -> list[str]:
    args: list[str] = [
        bwrap_executable,
        "--new-session",
        "--die-with-parent",
        "--unshare-user",
        "--unshare-pid",
    ]
    if not network_access:
        args.append("--unshare-net")

    for root in _resolve_read_roots(readable_roots):
        args.extend(["--ro-bind", str(root), str(root)])

    network_mounts = _resolve_network_read_mounts(readable_roots) if network_access else []
    if network_mounts:
        args.extend(["--dir", "/etc"])
        for source, target in network_mounts:
            args.extend(["--ro-bind", str(source), str(target)])

    args.extend(["--proc", "/proc", "--dev", "/dev"])

    if mode == "workspace-write":
        for writable_root in writable_roots:
            args.extend(["--bind", str(writable_root), str(writable_root)])

    for protected_root in _resolve_protected_roots(protected_roots):
        if protected_root.is_dir():
            args.extend(["--tmpfs", str(protected_root)])
        else:
            args.extend(["--ro-bind", "/dev/null", str(protected_root)])

    args.extend(
        [
            "--chdir",
            str(workspace),
            "--",
            "/usr/bin/bash",
            "--noprofile",
            "--norc",
            "-lc",
            command,
        ]
    )
    return args


def _resolve_read_roots(readable_roots: list[Path]) -> list[Path]:
    fixed_roots: list[Path] = [*(path.resolve() for path in readable_roots), *FIXED_READ_ROOTS]
    deduped: list[Path] = list(fixed_roots)
    for entry in os.environ.get("PATH", "").split(":"):
        if not entry:
            continue
        path = Path(entry).resolve()
        if not path.exists():
            continue
        candidates = [path]
        if path.name in {"bin", "sbin"}:
            parent = path.parent
            if parent.exists():
                candidates.append(parent.resolve())
        for candidate in candidates:
            if any(candidate == existing or _path_is_within(candidate, existing) for existing in deduped):
                continue
            deduped.append(candidate)
    return deduped


def _resolve_protected_roots(protected_roots: list[Path]) -> list[Path]:
    deduped: list[Path] = []
    seen: set[str] = set()
    for root in protected_roots:
        candidate = root.resolve()
        if not candidate.exists():
            continue
        key = str(candidate)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(candidate)
    return deduped


def _resolve_network_read_mounts(readable_roots: list[Path]) -> list[tuple[Path, Path]]:
    read_roots = [path.resolve() for path in readable_roots if path.exists()]
    if any(root == Path("/etc") or _path_is_within(Path("/etc"), root) for root in read_roots):
        return []

    mounts: list[tuple[Path, Path]] = []
    seen_targets: set[str] = set()
    for source, target in NETWORK_READ_MOUNTS:
        if not source.exists():
            continue
        resolved_source = source.resolve()
        if not resolved_source.exists():
            continue
        target_key = str(target)
        if target_key in seen_targets:
            continue
        seen_targets.add(target_key)
        mounts.append((resolved_source, target))
    return mounts


def _path_is_within(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False
