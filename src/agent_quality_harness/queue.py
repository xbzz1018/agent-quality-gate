import asyncio
import logging
from collections.abc import Awaitable, Callable

from redis.asyncio import Redis
from redis.exceptions import RedisError

logger = logging.getLogger(__name__)


class RedisRunQueue:
    def __init__(self, redis_url: str, queue_key: str) -> None:
        self.queue_key = f"{queue_key}:ready"
        self.processing_key = f"{queue_key}:processing"
        self.client = Redis.from_url(
            redis_url,
            decode_responses=True,
            socket_connect_timeout=5,
            socket_timeout=60,
            health_check_interval=30,
        )

    async def enqueue(self, run_id: int) -> None:
        await self.client.lpush(self.queue_key, str(run_id))

    async def claim(self, timeout_seconds: int) -> int | None:
        value = await self.client.brpoplpush(
            self.queue_key, self.processing_key, timeout=timeout_seconds
        )
        if value is None:
            return None
        return int(value)

    async def ack(self, run_id: int) -> None:
        await self.client.lrem(self.processing_key, 1, str(run_id))

    async def requeue(self, run_id: int) -> None:
        async with self.client.pipeline(transaction=True) as pipe:
            pipe.lrem(self.processing_key, 1, str(run_id))
            pipe.lpush(self.queue_key, str(run_id))
            await pipe.execute()

    async def processing_ids(self) -> list[int]:
        values = await self.client.lrange(self.processing_key, 0, -1)
        return [int(value) for value in values]

    async def ping(self) -> None:
        await self.client.ping()

    async def close(self) -> None:
        await self.client.aclose()


class RedisRunWorker:
    def __init__(
        self,
        queue: RedisRunQueue,
        execute_run: Callable[[int], Awaitable[None]],
        *,
        claim_timeout_seconds: int = 5,
    ) -> None:
        self.queue = queue
        self.execute_run = execute_run
        self.claim_timeout_seconds = claim_timeout_seconds

    async def process_once(self) -> bool:
        run_id = await self.queue.claim(self.claim_timeout_seconds)
        if run_id is None:
            return False
        try:
            await self.execute_run(run_id)
        except Exception:
            await self.queue.requeue(run_id)
            raise
        await self.queue.ack(run_id)
        return True

    async def run_forever(self) -> None:
        consecutive_errors = 0
        while True:
            try:
                await self.process_once()
                consecutive_errors = 0
            except asyncio.CancelledError:
                raise
            except RedisError:
                consecutive_errors += 1
                delay = min(2 ** (consecutive_errors - 1), 30)
                logger.exception("Redis queue error; retrying in %s seconds", delay)
                await asyncio.sleep(delay)
            await asyncio.sleep(0)
