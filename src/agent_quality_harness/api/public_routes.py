import httpx
from fastapi import APIRouter, HTTPException, Request, status

from .schemas import Readiness

router = APIRouter(tags=["health"])


@router.get("/health/live")
def live() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/health/ready", response_model=Readiness)
async def ready(request: Request) -> Readiness:
    components: dict[str, str] = {}
    try:
        request.app.state.database.ping()
        components["postgresql"] = "ok"
    except Exception:
        components["postgresql"] = "unavailable"
    try:
        await request.app.state.run_queue.ping()
        component = getattr(
            request.app.state.run_queue,
            "readiness_component",
            request.app.state.settings.queue_backend,
        )
        components[component] = "ok"
    except Exception:
        component = getattr(
            request.app.state.run_queue,
            "readiness_component",
            request.app.state.settings.queue_backend,
        )
        components[component] = "unavailable"
    if request.app.state.settings.opa_enabled:
        try:
            async with httpx.AsyncClient(
                timeout=request.app.state.settings.opa_timeout_seconds
            ) as client:
                response = await client.get(
                    f"{request.app.state.settings.opa_url.rstrip('/')}/health"
                )
                response.raise_for_status()
            components["opa"] = "ok"
        except Exception:
            components["opa"] = "unavailable"
    if all(value == "ok" for value in components.values()):
        return Readiness(status="ready", components=components)
    raise HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail=Readiness(status="not_ready", components=components).model_dump(),
    )
