from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from typing import Any

from backend.plugin_runtime.service import PluginService


class HookManager:
    def __init__(self, plugin_service: PluginService):
        self.plugin_service = plugin_service

    def messages_for(self, event: str) -> list[str]:
        return self.plugin_service.hook_messages(event)

    async def handler_messages_for(self, event: str, context: dict[str, Any]) -> list[str]:
        messages: list[str] = []
        for plugin, hook in self.plugin_service.hooks_for(event):
            handler = getattr(hook, "handler", None)
            if not handler:
                continue
            hook_path = (plugin.root_path / str(handler)).resolve()
            payload = await _run_hook_handler(
                hook_path,
                plugin_name=plugin.manifest.name,
                event=event,
                timeout_seconds=int(getattr(hook, "timeout_seconds", 5)),
                context=context,
            )
            if payload:
                messages.extend(payload)
        return messages


async def _run_hook_handler(
    hook_path: Path,
    *,
    plugin_name: str,
    event: str,
    timeout_seconds: int,
    context: dict[str, Any],
) -> list[str]:
    proc = await asyncio.create_subprocess_exec(
        sys.executable,
        str(hook_path),
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=str(hook_path.parent),
    )
    payload = json.dumps({"event": event, "plugin": plugin_name, "context": context}, ensure_ascii=False).encode("utf-8")
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(payload), timeout=timeout_seconds)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.communicate()
        return [f"{plugin_name}: hook handler timed out for {event}"]

    stdout_text = stdout.decode("utf-8", errors="replace").strip()
    stderr_text = stderr.decode("utf-8", errors="replace").strip()
    if proc.returncode != 0:
        detail = stderr_text or stdout_text or f"exit code {proc.returncode}"
        return [f"{plugin_name}: hook handler failed for {event}: {detail}"]
    if not stdout_text:
        return []
    return [f"{plugin_name}: {line.strip()}" for line in stdout_text.splitlines() if line.strip()]
