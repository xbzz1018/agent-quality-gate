from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import Depends, FastAPI

from agent_quality_harness.api.admin_routes import router as admin_router
from agent_quality_harness.api.analytics_routes import router as analytics_router
from agent_quality_harness.api.auth_routes import router as auth_router
from agent_quality_harness.api.dependencies import require_organization
from agent_quality_harness.api.public_routes import router as public_router
from agent_quality_harness.api.routes import router
from agent_quality_harness.api.scenario_routes import router as scenario_router
from agent_quality_harness.api.security_routes import router as security_router
from agent_quality_harness.core.config import Settings, get_settings
from agent_quality_harness.core.database import Database
from agent_quality_harness.core.telemetry import configure_telemetry
from agent_quality_harness.queue import RedisRunQueue


def create_app(
    settings: Settings | None = None,
    *,
    database: Any | None = None,
    run_queue: Any | None = None,
    scenario_queue: Any | None = None,
) -> FastAPI:
    settings = settings or get_settings()
    database = database or Database(settings.database_url)
    if run_queue is None:
        if settings.queue_backend == "kafka":
            from agent_quality_harness.outbox_queue import OutboxRunQueue

            run_queue = OutboxRunQueue(database)
        else:
            run_queue = RedisRunQueue(settings.redis_url, settings.redis_queue_key)
    scenario_queue = scenario_queue or RedisRunQueue(
        settings.redis_url, settings.redis_scenario_queue_key
    )

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        yield
        close_queue = getattr(run_queue, "close", None)
        if close_queue is not None:
            await close_queue()
        close_scenario_queue = getattr(scenario_queue, "close", None)
        if close_scenario_queue is not None:
            await close_scenario_queue()
        close_database = getattr(database, "close", None)
        if close_database is not None:
            close_database()

    app = FastAPI(title=settings.app_name, version="0.5.0", lifespan=lifespan)
    app.state.settings = settings
    app.state.database = database
    app.state.run_queue = run_queue
    app.state.scenario_queue = scenario_queue
    app.include_router(public_router, prefix=settings.api_prefix)
    app.include_router(auth_router, prefix=settings.api_prefix)
    app.include_router(admin_router, prefix=settings.api_prefix)
    app.include_router(
        router,
        prefix=settings.api_prefix,
        dependencies=[Depends(require_organization)],
    )
    app.include_router(
        analytics_router,
        prefix=settings.api_prefix,
        dependencies=[Depends(require_organization)],
    )
    app.include_router(
        security_router,
        prefix=settings.api_prefix,
        dependencies=[Depends(require_organization)],
    )
    app.include_router(
        scenario_router,
        prefix=settings.api_prefix,
        dependencies=[Depends(require_organization)],
    )
    configure_telemetry(app, settings)
    return app


app = create_app()
