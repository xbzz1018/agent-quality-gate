import asyncio

from aiokafka.admin import AIOKafkaAdminClient

from agent_quality_harness.core.config import get_settings
from agent_quality_harness.core.database import Database


async def check() -> None:
    settings = get_settings()
    database = Database(settings.database_url)
    admin = AIOKafkaAdminClient(bootstrap_servers=settings.kafka_bootstrap_servers)
    try:
        await asyncio.to_thread(database.ping)
        await admin.start()
    finally:
        await admin.close()
        database.close()


def main() -> None:
    asyncio.run(check())


if __name__ == "__main__":
    main()
