from __future__ import annotations

from pathlib import Path
from typing import Iterable, Mapping, Sequence

from backend.sandbox.models import ConfinedArgv, ProviderHealth, SandboxPolicy
from backend.sandbox.registry import health_from_native


class NativeSandboxProvider:
    """Adapter exposing the proven NativeSandbox facade as a v2 provider."""

    def __init__(self, native_sandbox):
        self.native = native_sandbox
        self.name = "linux_bwrap"

    def probe(self, policy: SandboxPolicy) -> ProviderHealth:
        return health_from_native(self.native)

    def confine(self, argv: Sequence[str], policy: SandboxPolicy) -> ConfinedArgv:
        wrapped, _env, _cwd, sandboxed, _filtered = self.native.prepare_argv(
            argv,
            cwd=policy.cwd,
            mode=policy.mode,
            network_access=policy.network_access,
            extra_readable_roots=policy.readable_roots,
            extra_writable_roots=policy.writable_roots,
        )
        health = self.probe(policy)
        return ConfinedArgv(
            argv=tuple(wrapped),
            backend=health.backend if sandboxed else "none",
            file_enforcement=health.file_enforcement if sandboxed else "unsupported",
            network_enforcement=health.network_enforcement if sandboxed else "unsupported",
            process_enforcement=health.process_enforcement if sandboxed else "unsupported",
            process_visibility_enforcement=health.process_visibility_enforcement if sandboxed else "unsupported",
            process_lifecycle_enforcement=health.process_lifecycle_enforcement if sandboxed else "unsupported",
            resource_enforcement=health.resource_enforcement if sandboxed else "unsupported",
            notes=("native facade adapter",),
        )


class UnsupportedSandboxProvider:
    """Explicit provider for a configured backend not available in this build."""

    def __init__(self, name: str, detail: str):
        self.name = name
        self.detail = detail

    def probe(self, policy: SandboxPolicy) -> ProviderHealth:
        return ProviderHealth(
            available=False,
            backend=self.name,
            file_enforcement="unsupported",
            network_enforcement="unsupported",
            process_enforcement="unsupported",
            resource_enforcement="unsupported",
            detail=self.detail,
        )

    def confine(self, argv: Sequence[str], policy: SandboxPolicy) -> ConfinedArgv:
        from backend.sandbox.native_sandbox import SandboxUnavailableError

        raise SandboxUnavailableError("SANDBOX_UNAVAILABLE", self.detail)
