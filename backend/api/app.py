from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.api.auth_utils import announce_bootstrap_state
from backend.api.health import build_healthz_payload
from backend.api.middleware.auth import auth_middleware
from backend.api.middleware.error_handler import install_error_handlers
from backend.api.middleware.request_id import request_id_middleware
from backend.api.routes.approvals import router as approvals_router
from backend.api.routes.audit import router as audit_router
from backend.api.routes.auth import router as auth_router
from backend.api.routes.bootstrap import router as bootstrap_router
from backend.api.routes.channels import router as channels_router
from backend.api.routes.config import router as config_router
from backend.api.routes.evolution import router as evolution_router
from backend.api.routes.mcp import router as mcp_router
from backend.api.routes.messages import router as messages_router
from backend.api.routes.plugins import router as plugins_router
from backend.api.routes.plugin_drafts import router as plugin_drafts_router
from backend.api.routes.runtime_location import router as runtime_location_router
from backend.api.routes.scheduler import router as scheduler_router
from backend.api.routes.sessions import router as sessions_router
from backend.api.routes.skills import router as skills_router
from backend.api.routes.subagents import router as subagents_router
from backend.api.routes.tools import router as tools_router
from backend.api.routes.usage import router as usage_router
from backend.api.routes.workspace import router as workspace_router
from backend.api.sse.channel_event_broker import ChannelEventBroker
from backend.channels.service import ChannelService
from backend.config.loader import get_settings, log_settings_report
from backend.runtime.run_loop import NewmanRuntime
from backend.scheduler.scheduler_engine import SchedulerEngine


def create_app() -> FastAPI:
    settings = get_settings()
    log_settings_report()
    announce_bootstrap_state(settings)
    app = FastAPI(title="Newman API", version="0.6.0")
    app.state.project_root = Path(__file__).resolve().parents[2]
    app.state.active_message_runs = {}
    app.state.settings = settings
    app.state.runtime = NewmanRuntime(settings, project_root=app.state.project_root)
    app.state.scheduler = SchedulerEngine(app.state.runtime.scheduler_store, app.state.runtime)
    app.state.channel_events = ChannelEventBroker()
    app.state.runtime.tool_context.scheduler_engine = app.state.scheduler
    if hasattr(app.state.scheduler, "set_session_busy_checker"):
        app.state.scheduler.set_session_busy_checker(lambda session_id: session_id in app.state.active_message_runs)
    app.state.channels = ChannelService(settings, app.state.runtime, event_broker=app.state.channel_events)

    app.middleware("http")(auth_middleware)
    app.middleware("http")(request_id_middleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.server.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    install_error_handlers(app)

    app.include_router(auth_router)
    app.include_router(bootstrap_router)
    app.include_router(sessions_router)
    app.include_router(messages_router)
    app.include_router(subagents_router)
    app.include_router(approvals_router)
    app.include_router(audit_router)
    app.include_router(config_router)
    app.include_router(workspace_router)
    app.include_router(plugins_router)
    app.include_router(plugin_drafts_router)
    app.include_router(skills_router)
    app.include_router(tools_router)
    app.include_router(runtime_location_router)
    app.include_router(usage_router)
    app.include_router(evolution_router)
    app.include_router(mcp_router)
    app.include_router(scheduler_router)
    app.include_router(channels_router)

    @app.on_event("startup")
    async def start_scheduler() -> None:
        app.state.runtime.reload_ecosystem()
        app.state.scheduler.refresh_schedule()
        await app.state.scheduler.start()
        if hasattr(app.state.channels, "start"):
            await app.state.channels.start()

    @app.on_event("shutdown")
    async def stop_scheduler() -> None:
        if hasattr(app.state.channels, "stop"):
            await app.state.channels.stop()
        await app.state.scheduler.stop()
        app.state.runtime.close()

    @app.get("/healthz")
    async def healthz():
        return build_healthz_payload(
            app_version=app.version,
            settings=settings,
            runtime=app.state.runtime,
            scheduler=app.state.scheduler,
            channels=app.state.channels,
        )

    @app.get("/readyz")
    async def readyz():
        return {
            "ok": True,
            "sessions_dir": str(settings.paths.sessions_dir),
            "plugins_dir": str(settings.paths.plugins_dir),
            "skills_dir": str(settings.paths.skills_dir),
            "mcp_dir": str(settings.paths.mcp_dir),
            "scheduler_dir": str(settings.paths.scheduler_dir),
            "channels_dir": str(settings.paths.channels_dir),
        }

    return app


app = create_app()
