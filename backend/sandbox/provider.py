from __future__ import annotations

from typing import Mapping, Protocol, Sequence

from backend.sandbox.models import ConfinedArgv, PreparedSandboxInvocation, ProviderHealth, SandboxPolicy


class SandboxProvider(Protocol):
    """Provider contract for backends such as linux_bwrap or future Landlock."""

    name: str

    def probe(self, policy: SandboxPolicy) -> ProviderHealth:
        ...

    def confine(self, argv: Sequence[str], policy: SandboxPolicy) -> ConfinedArgv:
        ...

    def prepare(
        self,
        argv: Sequence[str],
        policy: SandboxPolicy,
        env: Mapping[str, str] | None = None,
    ) -> PreparedSandboxInvocation:
        ...
