from __future__ import annotations

import sys
from typing import Iterable

from backend.sandbox.models import ProviderHealth


def health_from_native(native_sandbox) -> ProviderHealth:
    """Adapt the migration-period NativeSandbox health object to v2 provider health."""

    health = native_sandbox.health()
    return ProviderHealth(
        available=bool(health.available),
        backend=str(health.selected_backend),
        file_enforcement=_enforcement(health.file_enforcement),
        network_enforcement=_enforcement(health.network_enforcement),
        process_enforcement=_enforcement(health.process_enforcement),
        resource_enforcement=_enforcement(health.resource_enforcement),
        process_visibility_enforcement=_enforcement(health.process_enforcement),
        process_lifecycle_enforcement=_enforcement(health.process_enforcement),
        detail=health.probe_error,
    )


def _enforcement(value: str) -> str:
    return value if value in {"full", "partial", "unsupported"} else "unsupported"


class SandboxProviderRegistry:
    """Select one explicitly registered provider and never silently fallback."""

    def __init__(self, providers: Iterable[object] = ()):
        self._providers: dict[str, object] = {}
        for provider in providers:
            self.register(provider)

    def register(self, provider: object) -> None:
        name = str(getattr(provider, "name", "")).strip()
        if not name:
            raise ValueError("sandbox provider must declare a non-empty name")
        self._providers[name] = provider

    def get(self, name: str) -> object | None:
        return self._providers.get(name)

    def select(self, configured_backend: str = "auto") -> object:
        from backend.sandbox.native_provider import UnsupportedSandboxProvider

        if configured_backend != "auto":
            expected_platform = _backend_platform(configured_backend)
            if expected_platform is not None and expected_platform != _current_platform_family():
                return UnsupportedSandboxProvider(
                    configured_backend,
                    f"sandbox backend {configured_backend} is unsupported on platform {sys.platform}",
                )
            return self._providers.get(configured_backend) or UnsupportedSandboxProvider(
                configured_backend,
                f"sandbox backend is not registered: {configured_backend}",
            )

        platform_family = _current_platform_family()
        if platform_family == "linux":
            preference = ("linux_bwrap", "linux_landlock")
        elif platform_family == "darwin":
            preference = ("macos_seatbelt",)
        elif platform_family == "win32":
            preference = ("windows_acl",)
        else:
            preference = ()
        for name in preference:
            provider = self._providers.get(name)
            if provider is not None:
                return provider
        return UnsupportedSandboxProvider("none", f"no sandbox provider registered for platform {sys.platform}")

    def probe(self, policy, configured_backend: str = "auto") -> ProviderHealth:
        provider = self.select(configured_backend)
        return provider.probe(policy)


def _current_platform_family() -> str:
    if sys.platform.startswith("linux"):
        return "linux"
    if sys.platform == "darwin":
        return "darwin"
    if sys.platform == "win32":
        return "win32"
    return sys.platform


def _backend_platform(backend: str) -> str | None:
    if backend in {"linux_bwrap", "linux_landlock"}:
        return "linux"
    if backend == "macos_seatbelt":
        return "darwin"
    if backend == "windows_acl":
        return "win32"
    return None
