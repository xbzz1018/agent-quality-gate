import asyncio

from agent_quality_harness.core.config import get_settings
from agent_quality_harness.core.database import Database
from agent_quality_harness.core.telemetry import configure_tracing
from agent_quality_harness.evaluation import InspectHarness
from agent_quality_harness.execution import InspectRunExecutor
from agent_quality_harness.policy import OpaClient
from agent_quality_harness.queue import RedisRunQueue, RedisRunWorker


async def run_worker() -> None:
    settings = get_settings()
    configure_tracing(settings, settings.otel_worker_service_name)
    database = Database(settings.database_url)
    queue = RedisRunQueue(settings.redis_url, settings.redis_queue_key)
    harness = InspectHarness(
        max_samples=settings.inspect_max_samples,
        log_dir=settings.inspect_log_dir,
    )
    executor = InspectRunExecutor(
        database,
        harness,
        lease_seconds=settings.worker_lease_seconds,
        heartbeat_seconds=settings.worker_heartbeat_seconds,
        opa_client=OpaClient(
            settings.opa_url,
            timeout_seconds=settings.opa_timeout_seconds,
        ),
    )
    worker = RedisRunWorker(
        queue,
        executor.execute,
        claim_timeout_seconds=settings.redis_claim_timeout_seconds,
    )
    try:
        for run_id in await queue.processing_ids():
            if executor.is_recoverable(run_id):
                await queue.requeue(run_id)
        await worker.run_forever()
    finally:
        await queue.close()
        database.close()


def main() -> None:
    asyncio.run(run_worker())


if __name__ == "__main__":
    main()
