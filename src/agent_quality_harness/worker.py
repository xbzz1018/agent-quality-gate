import asyncio

from agent_quality_harness.core.config import get_settings
from agent_quality_harness.core.database import Database
from agent_quality_harness.core.telemetry import configure_tracing
from agent_quality_harness.evaluation import InspectHarness
from agent_quality_harness.execution import InspectRunExecutor
from agent_quality_harness.judging import (
    DisabledHallucinationJudge,
    OpenAICompatibleHallucinationJudge,
)
from agent_quality_harness.policy import OpaClient
from agent_quality_harness.queue import RedisRunQueue, RedisRunWorker
from agent_quality_harness.scenario_runtime import ScenarioRuntimeExecutor


async def run_worker() -> None:
    settings = get_settings()
    configure_tracing(settings, settings.otel_worker_service_name)
    database = Database(settings.database_url)
    queue = RedisRunQueue(settings.redis_url, settings.redis_queue_key)
    scenario_queue = RedisRunQueue(settings.redis_url, settings.redis_scenario_queue_key)
    judge = DisabledHallucinationJudge()
    if settings.judge_enabled and settings.judge_api_key is not None:
        judge = OpenAICompatibleHallucinationJudge(
            base_url=settings.judge_base_url,
            model=settings.judge_model,
            api_key=settings.judge_api_key.get_secret_value(),
            timeout_seconds=settings.judge_timeout_seconds,
        )
    harness = InspectHarness(
        max_samples=settings.inspect_max_samples,
        log_dir=settings.inspect_log_dir,
        judge=judge,
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
    scenario_executor = ScenarioRuntimeExecutor(
        database,
        lease_seconds=settings.worker_lease_seconds,
        heartbeat_seconds=settings.worker_heartbeat_seconds,
    )
    scenario_worker = RedisRunWorker(
        scenario_queue,
        scenario_executor.execute,
        claim_timeout_seconds=settings.redis_claim_timeout_seconds,
    )
    try:
        for run_id in await queue.processing_ids():
            if executor.is_recoverable(run_id):
                await queue.requeue(run_id)
        for run_id in await scenario_queue.processing_ids():
            if scenario_executor.is_recoverable(run_id):
                await scenario_queue.requeue(run_id)
        await asyncio.gather(worker.run_forever(), scenario_worker.run_forever())
    finally:
        await queue.close()
        await scenario_queue.close()
        database.close()


def main() -> None:
    asyncio.run(run_worker())


if __name__ == "__main__":
    main()
