import asyncio

from agent_quality_harness.core.config import get_settings
from agent_quality_harness.core.database import Database
from agent_quality_harness.kafka_queue import KafkaOutboxPublisher


async def run_publisher() -> None:
    settings = get_settings()
    database = Database(settings.database_url)
    publisher = KafkaOutboxPublisher(
        database,
        bootstrap_servers=settings.kafka_bootstrap_servers,
        topic=settings.kafka_run_topic,
        max_attempts=settings.kafka_max_attempts,
    )
    try:
        await publisher.run_forever()
    finally:
        database.close()


def main() -> None:
    asyncio.run(run_publisher())


if __name__ == "__main__":
    main()
