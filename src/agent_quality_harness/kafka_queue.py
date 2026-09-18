from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable, Mapping
from datetime import UTC, datetime, timedelta
from typing import Any

from aiokafka import AIOKafkaConsumer, AIOKafkaProducer, TopicPartition
from sqlalchemy import or_, select

from agent_quality_harness.core.database import Database
from agent_quality_harness.domain.models import KafkaDlq, KafkaInbox, OutboxEvent


class KafkaOutboxPublisher:
    def __init__(
        self,
        database: Database,
        *,
        bootstrap_servers: str,
        topic: str,
        max_attempts: int = 3,
        lease_seconds: int = 30,
        producer: AIOKafkaProducer | None = None,
    ) -> None:
        self.database = database
        self.bootstrap_servers = bootstrap_servers
        self.topic = topic
        self.max_attempts = max_attempts
        self.lease_seconds = lease_seconds
        self.producer = producer
        self._owned = producer is None

    async def start(self) -> None:
        if self.producer is None:
            self.producer = AIOKafkaProducer(bootstrap_servers=self.bootstrap_servers)
        if self._owned:
            await self.producer.start()

    async def stop(self) -> None:
        if self._owned and self.producer is not None:
            await self.producer.stop()

    async def publish_once(self) -> bool:
        claimed = await asyncio.to_thread(self._claim)
        if claimed is None:
            return False
        event_id, payload = claimed
        assert self.producer is not None
        try:
            await self.producer.send_and_wait(
                self.topic,
                json.dumps(payload, sort_keys=True, separators=(",", ":")).encode(),
                key=event_id.encode(),
            )
        except Exception as error:
            await asyncio.to_thread(self._mark_publish_error, event_id, type(error).__name__)
            return False
        await asyncio.to_thread(self._mark_published, event_id)
        return True

    async def run_forever(self) -> None:
        await self.start()
        try:
            while True:
                published = await self.publish_once()
                if not published:
                    await asyncio.sleep(0.5)
        finally:
            await self.stop()

    def _claim(self) -> tuple[str, dict[str, Any]] | None:
        now = datetime.now(UTC)
        with self.database.session() as session:
            event = session.scalar(
                select(OutboxEvent)
                .where(
                    or_(
                        (OutboxEvent.status == "pending") & (OutboxEvent.available_at <= now),
                        (OutboxEvent.status == "publishing") & (OutboxEvent.available_at <= now),
                    )
                )
                .order_by(OutboxEvent.created_at)
                .with_for_update(skip_locked=True)
                .limit(1)
            )
            if event is None:
                return None
            event.status = "publishing"
            event.attempts += 1
            event.available_at = now + timedelta(seconds=self.lease_seconds)
            payload = {
                "event_id": event.event_id,
                "event_type": event.event_type,
                "organization_id": event.organization_id,
                "run_id": event.run_id,
                "payload": event.payload,
                "created_at": event.created_at.isoformat(),
            }
            session.commit()
            return event.event_id, payload

    def _mark_published(self, event_id: str) -> None:
        with self.database.session() as session:
            event = session.get(OutboxEvent, event_id)
            if event is None:
                return
            event.status = "published"
            event.published_at = datetime.now(UTC)
            event.last_error_type = None
            session.commit()

    def _mark_publish_error(self, event_id: str, error_type: str) -> None:
        with self.database.session() as session:
            event = session.get(OutboxEvent, event_id)
            if event is None:
                return
            event.last_error_type = error_type[:100]
            if event.attempts >= self.max_attempts:
                event.status = "failed"
                session.merge(
                    KafkaDlq(
                        event_id=event.event_id,
                        run_id=event.run_id,
                        payload=event.payload,
                        attempts=event.attempts,
                        error_type=event.last_error_type,
                    )
                )
            else:
                event.status = "pending"
                event.available_at = datetime.now(UTC) + timedelta(
                    seconds=min(2**event.attempts, 30)
                )
            session.commit()


class KafkaRunWorker:
    def __init__(
        self,
        database: Database,
        execute_run: Callable[[int], Awaitable[None]],
        *,
        bootstrap_servers: str,
        topic: str,
        dlq_topic: str,
        consumer_group: str,
        max_attempts: int = 3,
    ) -> None:
        self.database = database
        self.execute_run = execute_run
        self.bootstrap_servers = bootstrap_servers
        self.topic = topic
        self.dlq_topic = dlq_topic
        self.consumer_group = consumer_group
        self.max_attempts = max_attempts

    async def process_event(
        self,
        event: Mapping[str, Any],
        *,
        publish_dlq: Callable[[bytes, bytes], Awaitable[Any]] | None = None,
    ) -> str:
        event_id = str(event.get("event_id", ""))
        run_id = int(event.get("run_id", 0))
        if not event_id or run_id <= 0:
            raise ValueError("Kafka EvalRun event is malformed")
        if await asyncio.to_thread(self._processed, event_id):
            return "duplicate"
        if event.get("event_type") != "eval_run.queued":
            await asyncio.to_thread(self._record_failure, event_id, run_id, event, "event_type")
            if publish_dlq is not None:
                await publish_dlq(event_id.encode(), _json_bytes(event))
            return "dlq"
        try:
            await self.execute_run(run_id)
        except Exception as error:
            attempts = await asyncio.to_thread(
                self._record_failure, event_id, run_id, event, type(error).__name__
            )
            if attempts < self.max_attempts:
                raise
            if publish_dlq is not None:
                await publish_dlq(event_id.encode(), _json_bytes(event))
            return "dlq"
        await asyncio.to_thread(self._mark_processed, event_id, run_id)
        return "processed"

    async def run_forever(self) -> None:
        consumer = AIOKafkaConsumer(
            self.topic,
            bootstrap_servers=self.bootstrap_servers,
            group_id=self.consumer_group,
            enable_auto_commit=False,
            auto_offset_reset="earliest",
        )
        producer = AIOKafkaProducer(bootstrap_servers=self.bootstrap_servers)
        await consumer.start()
        await producer.start()
        try:
            async for record in consumer:
                partition = TopicPartition(record.topic, record.partition)
                try:
                    event = json.loads(record.value)
                    await self.process_event(
                        event,
                        publish_dlq=lambda key, value: producer.send_and_wait(
                            self.dlq_topic, value, key=key
                        ),
                    )
                    await consumer.commit()
                except Exception:
                    consumer.seek(partition, record.offset)
                    await asyncio.sleep(1)
        finally:
            await producer.stop()
            await consumer.stop()

    def _processed(self, event_id: str) -> bool:
        with self.database.session() as session:
            return (
                session.scalar(
                    select(KafkaInbox.id).where(
                        KafkaInbox.consumer_group == self.consumer_group,
                        KafkaInbox.event_id == event_id,
                    )
                )
                is not None
            )

    def _mark_processed(self, event_id: str, run_id: int) -> None:
        with self.database.session() as session:
            if (
                session.scalar(
                    select(KafkaInbox.id).where(
                        KafkaInbox.consumer_group == self.consumer_group,
                        KafkaInbox.event_id == event_id,
                    )
                )
                is None
            ):
                session.add(
                    KafkaInbox(
                        consumer_group=self.consumer_group,
                        event_id=event_id,
                        run_id=run_id,
                    )
                )
                session.commit()

    def _record_failure(
        self,
        event_id: str,
        run_id: int,
        payload: Mapping[str, Any],
        error_type: str,
    ) -> int:
        with self.database.session() as session:
            record = session.get(KafkaDlq, event_id)
            if record is None:
                record = KafkaDlq(
                    event_id=event_id,
                    run_id=run_id,
                    payload=dict(payload),
                    attempts=0,
                    error_type=error_type[:100],
                )
                session.add(record)
            record.attempts += 1
            record.error_type = error_type[:100]
            record.failed_at = datetime.now(UTC)
            session.commit()
            return record.attempts


def _json_bytes(value: Mapping[str, Any]) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
