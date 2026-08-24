import asyncio

import httpx
from redis.asyncio import Redis

from agent_quality_harness.core.config import get_settings
from agent_quality_harness.core.database import Database


async def check() -> None:
    settings = get_settings()
    database = Database(settings.database_url)
    redis = Redis.from_url(settings.redis_url)
    try:
        await asyncio.to_thread(database.ping)
        await redis.ping()
        if settings.opa_enabled:
            async with httpx.AsyncClient(timeout=settings.opa_timeout_seconds) as client:
                response = await client.get(f"{settings.opa_url.rstrip('/')}/health")
                response.raise_for_status()
    finally:
        await redis.aclose()
        database.close()


def main() -> None:
    asyncio.run(check())


if __name__ == "__main__":
    main()
