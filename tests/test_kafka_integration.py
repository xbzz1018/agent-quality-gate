import json
import os
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from aiokafka import AIOKafkaConsumer
from aiokafka.admin import AIOKafkaAdminClient, NewTopic
from sqlalchemy import delete, select

from agent_quality_harness.core.database import Database
from agent_quality_harness.domain.enums import RunStatus, TargetKind, TargetProtocol
from agent_quality_harness.domain.models import (
    AgentVersion,
    EvalCase,
    EvalDataset,
    EvalRun,
    EvaluationTarget,
    KafkaDlq,
    KafkaInbox,
    Organization,
    OutboxEvent,
)
from agent_quality_harness.kafka_queue import KafkaOutboxPublisher, KafkaRunWorker

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        os.getenv("AQH_RUN_KAFKA_INTEGRATION") != "1",
        reason="set AQH_RUN_KAFKA_INTEGRATION=1 with PostgreSQL and Kafka running",
    ),
]


async def test_real_kafka_outbox_consumer_idempotency_and_dlq() -> None:
    suffix = uuid4().hex[:10]
    topic = f"aqh.integration.{suffix}"
    group = f"aqh-integration-{suffix}"
    database = Database(
        "postgresql+psycopg://agent_quality:agent_quality@localhost:5432/agent_quality"
    )
    event_id = str(uuid4())
    dlq_event_id = str(uuid4())
    created: dict[str, int] = {}
    with database.session() as session:
        organization = Organization(slug=f"kafka-{suffix}", name=f"Kafka {suffix}")
        session.add(organization)
        session.flush()
        target = EvaluationTarget(
            organization_id=organization.id,
            name=f"kafka-{suffix}",
            target_kind=TargetKind.AGENT,
            protocol=TargetProtocol.HTTP,
            endpoint="http://unused",
            timeout_seconds=30,
            capabilities={},
            enabled=True,
        )
        session.add(target)
        session.flush()
        version = AgentVersion(target_id=target.id, version="v1", metadata_json={})
        dataset = EvalDataset(
            organization_id=organization.id,
            name=f"kafka-{suffix}",
            version="v1",
            split="test",
            sha256="a" * 64,
            frozen_at=datetime.now(UTC),
            provenance={},
        )
        session.add_all([version, dataset])
        session.flush()
        case = EvalCase(
            dataset_id=dataset.id,
            ordinal=0,
            external_id="case-1",
            input_data={},
            expected={},
            tags=[],
            sha256="b" * 64,
        )
        session.add(case)
        session.flush()
        run = EvalRun(
            organization_id=organization.id,
            dataset_id=dataset.id,
            candidate_version_id=version.id,
            status=RunStatus.QUEUED,
            config={"queue_backend": "kafka"},
            manifest={},
            benchmark_mode=False,
            expected_case_count=1,
            completed_case_count=0,
        )
        session.add(run)
        session.flush()
        session.add(
            OutboxEvent(
                event_id=event_id,
                organization_id=organization.id,
                run_id=run.id,
                event_type="eval_run.queued",
                payload={"run_id": run.id},
                status="pending",
                attempts=0,
                available_at=datetime.now(UTC),
            )
        )
        session.commit()
        created = {"organization": organization.id, "run": run.id}

    publisher = KafkaOutboxPublisher(
        database,
        bootstrap_servers="localhost:29092",
        topic=topic,
    )
    consumer = AIOKafkaConsumer(
        topic,
        bootstrap_servers="localhost:29092",
        group_id=group,
        auto_offset_reset="earliest",
    )
    executed: list[int] = []

    async def execute(run_id: int) -> None:
        executed.append(run_id)

    worker = KafkaRunWorker(
        database,
        execute,
        bootstrap_servers="localhost:29092",
        topic=topic,
        dlq_topic=f"{topic}.dlq",
        consumer_group=group,
    )
    admin = AIOKafkaAdminClient(bootstrap_servers="localhost:29092")
    try:
        await admin.start()
        await admin.create_topics(
            [
                NewTopic(name=topic, num_partitions=1, replication_factor=1),
                NewTopic(name=f"{topic}.dlq", num_partitions=1, replication_factor=1),
            ]
        )
        await consumer.start()
        await publisher.start()
        assert await publisher.publish_once() is True
        record = await consumer.getone()
        event = json.loads(record.value)
        assert await worker.process_event(event) == "processed"
        assert await worker.process_event(event) == "duplicate"
        dlq_messages: list[tuple[bytes, bytes]] = []

        async def capture_dlq(key: bytes, value: bytes) -> None:
            dlq_messages.append((key, value))

        assert (
            await worker.process_event(
                {
                    "event_id": dlq_event_id,
                    "event_type": "unknown.event",
                    "run_id": created["run"],
                },
                publish_dlq=capture_dlq,
            )
            == "dlq"
        )
        assert executed == [created["run"]]
        assert len(dlq_messages) == 1
        with database.session() as session:
            assert session.get(OutboxEvent, event_id).status == "published"
            assert session.scalar(
                select(KafkaInbox).where(
                    KafkaInbox.consumer_group == group,
                    KafkaInbox.event_id == event_id,
                )
            )
            assert session.get(KafkaDlq, dlq_event_id) is not None
    finally:
        await admin.close()
        await publisher.stop()
        await consumer.stop()
        with database.session() as session:
            session.execute(delete(KafkaInbox).where(KafkaInbox.consumer_group == group))
            session.execute(delete(KafkaDlq).where(KafkaDlq.event_id == dlq_event_id))
            organization = session.get(Organization, created.get("organization"))
            if organization is not None:
                session.delete(organization)
            session.commit()
        database.close()
