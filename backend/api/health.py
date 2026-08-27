from __future__ import annotations

from typing import Any


def build_healthz_payload(
    *,
    app_version: str,
    settings: Any,
    runtime: Any,
    scheduler: Any | None = None,
    channels: Any | None = None,
) -> dict[str, Any]:
    sandbox_health = runtime.sandbox_health() if hasattr(runtime, "sandbox_health") else None
    tools = [tool.meta.name for tool in runtime.registry.list_tools()]
    plugins_enabled = len([item for item in runtime.plugin_service.list_plugins() if item.enabled])
    scheduler_running = bool(getattr(scheduler, "_running", False)) if scheduler is not None else False
    channel_statuses = channels.list_status() if channels is not None and hasattr(channels, "list_status") else []
    return {
        "ok": True,
        "version": app_version,
        "provider": settings.provider.type,
        "deployment_profile": getattr(settings, "deployment_profile", "none"),
        "sandbox_enabled": settings.sandbox.enabled,
        "sandbox": sandbox_health,
        "tools": tools,
        "plugins_enabled": plugins_enabled,
        "scheduler_running": scheduler_running,
        "channels_enabled": len([item for item in channel_statuses if item["enabled"]]),
    }
