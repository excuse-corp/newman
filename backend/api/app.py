from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.api.middleware.error_handler import install_error_handlers
from backend.api.middleware.request_id import request_id_middleware
from backend.api.routes.approvals import router as approvals_router
from backend.api.routes.audit import router as audit_router
from backend.api.routes.channels import router as channels_router
from backend.api.routes.knowledge import router as knowledge_router
from backend.api.routes.mcp import router as mcp_router
from backend.api.routes.messages import router as messages_router
from backend.api.routes.plugins import router as plugins_router
from backend.api.routes.scheduler import router as scheduler_router
from backend.api.routes.sessions import router as sessions_router
from backend.api.routes.skills import router as skills_router
from backend.api.routes.workspace import router as workspace_router
from backend.channels.service import ChannelService
from backend.config.loader import get_settings
from backend.rag.service import KnowledgeBaseService
from backend.runtime.run_loop import NewmanRuntime
from backend.scheduler.scheduler_engine import SchedulerEngine


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title="Newman API", version="0.5.0")
    app.state.settings = settings
    app.state.runtime = NewmanRuntime(settings)
    app.state.scheduler = SchedulerEngine(app.state.runtime.scheduler_store, app.state.runtime)
    app.state.channels = ChannelService(settings, app.state.runtime)

    app.middleware("http")(request_id_middleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.server.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    install_error_handlers(app)

    app.include_router(sessions_router)
    app.include_router(messages_router)
    app.include_router(approvals_router)
    app.include_router(audit_router)
    app.include_router(knowledge_router)
    app.include_router(workspace_router)
    app.include_router(plugins_router)
    app.include_router(skills_router)
    app.include_router(mcp_router)
    app.include_router(scheduler_router)
    app.include_router(channels_router)

    @app.on_event("startup")
    async def start_scheduler() -> None:
        app.state.runtime.reload_ecosystem()
        app.state.scheduler.refresh_schedule()
        await app.state.scheduler.start()

    @app.on_event("shutdown")
    async def stop_scheduler() -> None:
        await app.state.scheduler.stop()

    @app.get("/healthz")
    async def healthz():
        runtime = app.state.runtime
        knowledge_base = KnowledgeBaseService(settings.paths.knowledge_dir, settings.paths.workspace)
        return {
            "ok": True,
            "version": app.version,
            "provider": settings.provider.type,
            "sandbox_enabled": settings.sandbox.enabled,
            "tools": [tool.meta.name for tool in runtime.registry.list_tools()],
            "knowledge_documents": len(knowledge_base.list_documents()),
            "plugins_enabled": len([item for item in runtime.plugin_service.list_plugins() if item.enabled]),
            "scheduler_running": bool(app.state.scheduler._running),
            "channels_enabled": len([item for item in app.state.channels.list_status() if item["enabled"]]),
        }

    @app.get("/readyz")
    async def readyz():
        return {
            "ok": True,
            "knowledge_dir": str(settings.paths.knowledge_dir),
            "sessions_dir": str(settings.paths.sessions_dir),
            "plugins_dir": str(settings.paths.plugins_dir),
            "skills_dir": str(settings.paths.skills_dir),
            "mcp_dir": str(settings.paths.mcp_dir),
            "scheduler_dir": str(settings.paths.scheduler_dir),
            "channels_dir": str(settings.paths.channels_dir),
        }

    return app


app = create_app()
