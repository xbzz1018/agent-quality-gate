import asyncio

from agent_quality_harness.core.database import Database


class OutboxRunQueue:
    """API facade for EvalRuns queued atomically through PostgreSQL Outbox."""

    readiness_component = "outbox"

    def __init__(self, database: Database) -> None:
        self.database = database

    async def enqueue(self, run_id: int) -> None:
        del run_id

    async def ping(self) -> None:
        await asyncio.to_thread(self.database.ping)

    async def close(self) -> None:
        return None
