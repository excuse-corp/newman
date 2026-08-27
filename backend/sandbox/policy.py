from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Iterable

from backend.sandbox.models import SandboxPolicy


def canonical_roots(paths: Iterable[Path]) -> tuple[str, ...]:
    """Return stable canonical roots for hashing and audit metadata."""

    values: list[str] = []
    seen: set[str] = set()
    for raw in paths:
        try:
            value = str(Path(raw).resolve(strict=False))
        except OSError:
            value = str(Path(raw).absolute())
        if value in seen:
            continue
        seen.add(value)
        values.append(value)
    return tuple(sorted(values))


def policy_hash(policy: SandboxPolicy, *, backend: str = "auto") -> str:
    """Compute the stable policy hash used by sandbox approval binding."""

    payload = {
        "backend": backend,
        "mode": policy.mode,
        "workspace_root": str(policy.workspace_root.resolve(strict=False)),
        "cwd": str(policy.cwd.resolve(strict=False)),
        "network_access": policy.network_access,
        "require_network_isolation": policy.require_network_isolation,
        "require_process_isolation": policy.require_process_isolation,
        "allow_partial_enforcement": policy.allow_partial_enforcement,
        "readable_roots": canonical_roots(policy.readable_roots),
        "writable_roots": canonical_roots(policy.writable_roots),
        "protected_roots": canonical_roots(policy.protected_roots),
        "source": policy.source,
    }
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def validate_policy(policy: SandboxPolicy) -> None:
    """Validate invariants that are independent of a concrete provider."""

    if policy.mode == "read-only" and policy.writable_roots:
        raise ValueError("read-only sandbox policy must not include writable_roots")
    if policy.mode == "danger-full-access":
        return

    workspace = policy.workspace_root.resolve(strict=False)
    cwd = policy.cwd.resolve(strict=False)
    visible_roots = [workspace, *policy.readable_roots, *policy.writable_roots]
    if not any(_is_relative_to(cwd, root.resolve(strict=False)) for root in visible_roots):
        raise ValueError(f"cwd is not visible under sandbox roots: {cwd}")

    protected = [root.resolve(strict=False) for root in policy.protected_roots]
    for writable in policy.writable_roots:
        writable_root = writable.resolve(strict=False)
        if any(_is_relative_to(writable_root, root) or _is_relative_to(root, writable_root) for root in protected):
            raise ValueError(f"writable root conflicts with protected root: {writable_root}")


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False
