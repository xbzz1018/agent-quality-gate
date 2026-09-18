import asyncio

from agent_quality_harness.core.config import get_settings
from agent_quality_harness.core.database import Database
from agent_quality_harness.core.telemetry import configure_tracing
from agent_quality_harness.evaluation import InspectHarness
from agent_quality_harness.execution import InspectRunExecutor
from agent_quality_harness.judging import DisabledHallucinationJudge
from agent_quality_harness.kafka_queue import KafkaRunWorker
from agent_quality_harness.policy import OpaClient


async def run_worker() -> None:
    settings = get_settings()
    configure_tracing(settings, settings.otel_worker_service_name)
    database = Database(settings.database_url)
    executor = InspectRunExecutor(
        database,
        InspectHarness(
            max_samples=settings.inspect_max_samples,
            log_dir=settings.inspect_log_dir,
            judge=DisabledHallucinationJudge(),
        ),
        lease_seconds=settings.worker_lease_seconds,
        heartbeat_seconds=settings.worker_heartbeat_seconds,
        opa_client=OpaClient(settings.opa_url, timeout_seconds=settings.opa_timeout_seconds),
    )
    worker = KafkaRunWorker(
        database,
        executor.execute,
        bootstrap_servers=settings.kafka_bootstrap_servers,
        topic=settings.kafka_run_topic,
        dlq_topic=settings.kafka_dlq_topic,
        consumer_group=settings.kafka_consumer_group,
        max_attempts=settings.kafka_max_attempts,
    )
    try:
        await worker.run_forever()
    finally:
        database.close()


def main() -> None:
    asyncio.run(run_worker())


if __name__ == "__main__":
    main()
