from __future__ import annotations

from backend.plugin_runtime.service import PluginService


class HookManager:
    def __init__(self, plugin_service: PluginService):
        self.plugin_service = plugin_service

    def messages_for(self, event: str) -> list[str]:
        return self.plugin_service.hook_messages(event)
