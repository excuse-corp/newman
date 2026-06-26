from __future__ import annotations

from pathlib import Path
from typing import Any

from backend.channels.service import ChannelService
from backend.config.loader import log_settings_report, reload_settings
from backend.runtime.run_loop import NewmanRuntime
from backend.scheduler.scheduler_engine import SchedulerEngine


async def reload_project_runtime(app: Any, project_root: Path) -> list[str]:
    previous_settings = app.state.settings
    previous_runtime = getattr(app.state, "runtime", None)
    previous_scheduler = getattr(app.state, "scheduler", None)
    previous_channels = getattr(app.state, "channels", None)

    next_settings = reload_settings(str(project_root))
    log_settings_report(str(project_root))
    warnings = _build_reload_warnings(previous_settings, next_settings)

    if previous_runtime is None or previous_scheduler is None or previous_channels is None:
        app.state.settings = next_settings
        return warnings

    next_runtime = NewmanRuntime(next_settings, project_root=project_root)
    next_scheduler = SchedulerEngine(next_runtime.scheduler_store, next_runtime)
    if hasattr(next_scheduler, "set_session_busy_checker"):
        next_scheduler.set_session_busy_checker(lambda session_id: session_id in app.state.active_message_runs)
    next_channels = ChannelService(next_settings, next_runtime, event_broker=getattr(app.state, "channel_events", None))
    next_runtime.reload_ecosystem()
    next_scheduler.refresh_schedule()

    await previous_scheduler.stop()
    if hasattr(previous_channels, "stop"):
        await previous_channels.stop()
    try:
        app.state.settings = next_settings
        app.state.runtime = next_runtime
        app.state.scheduler = next_scheduler
        app.state.channels = next_channels
        await next_scheduler.start()
        if hasattr(next_channels, "start"):
            await next_channels.start()
    except Exception:
        app.state.settings = previous_settings
        app.state.runtime = previous_runtime
        app.state.scheduler = previous_scheduler
        app.state.channels = previous_channels
        next_runtime.close()
        if hasattr(previous_channels, "start"):
            await previous_channels.start()
        await previous_scheduler.start()
        raise

    previous_runtime.close()
    return warnings


def _build_reload_warnings(previous_settings, next_settings) -> list[str]:
    warnings: list[str] = []
    if previous_settings.server.host != next_settings.server.host or previous_settings.server.port != next_settings.server.port:
        warnings.append("`server.host` / `server.port` 的变化需要重启进程后才能真正改变监听地址。")
    if previous_settings.server.cors_origins != next_settings.server.cors_origins:
        warnings.append("`server.cors_origins` 已写入配置，但现有 CORS 中间件需要重启进程后才会更新。")
    return warnings
