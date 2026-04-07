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


def resolve_bwrap_executable() -> str | None:
    return which("bwrap")


def build_bwrap_command(
    *,
    bwrap_executable: str,
    workspace: Path,
    writable_roots: list[Path],
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

    for root in _resolve_read_roots(workspace):
        args.extend(["--ro-bind", str(root), str(root)])

    args.extend(["--proc", "/proc", "--dev", "/dev"])

    if mode == "workspace-write":
        for writable_root in writable_roots:
            args.extend(["--bind", str(writable_root), str(writable_root)])

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


def _resolve_read_roots(workspace: Path) -> list[Path]:
    fixed_roots: list[Path] = [workspace.resolve(), *FIXED_READ_ROOTS]
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


def _path_is_within(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False
