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
        components["redis"] = "ok"
    except Exception:
        components["redis"] = "unavailable"
    if all(value == "ok" for value in components.values()):
        return Readiness(status="ready", components=components)
    raise HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail=Readiness(status="not_ready", components=components).model_dump(),
    )
