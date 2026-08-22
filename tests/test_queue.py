import asyncio

import pytest
from redis.exceptions import TimeoutError as RedisTimeoutError

from agent_quality_harness.queue import RedisRunWorker


class StubQueue:
    def __init__(self, run_id: int | None) -> None:
        self.run_id = run_id

    async def claim(self, timeout_seconds: int) -> int | None:
        assert timeout_seconds == 1
        value, self.run_id = self.run_id, None
        return value

    async def ack(self, run_id: int) -> None:
        assert run_id == 42

    async def requeue(self, run_id: int) -> None:
        self.run_id = run_id


async def test_worker_claims_one_whole_eval_run() -> None:
    executed: list[int] = []

    async def execute(run_id: int) -> None:
        executed.append(run_id)

    worker = RedisRunWorker(StubQueue(42), execute, claim_timeout_seconds=1)  # type: ignore[arg-type]

    assert await worker.process_once() is True
    assert await worker.process_once() is False
    assert executed == [42]


class FlakyQueue:
    def __init__(self) -> None:
        self.calls = 0

    async def claim(self, timeout_seconds: int) -> int | None:
        self.calls += 1
        if self.calls == 1:
            raise RedisTimeoutError("transient")
        return 7

    async def ack(self, run_id: int) -> None:
        assert run_id == 7

    async def requeue(self, run_id: int) -> None:
        assert run_id == 7


async def test_worker_retries_transient_redis_error() -> None:
    executed = asyncio.Event()

    async def execute(run_id: int) -> None:
        assert run_id == 7
        executed.set()

    worker = RedisRunWorker(FlakyQueue(), execute, claim_timeout_seconds=1)  # type: ignore[arg-type]
    task = asyncio.create_task(worker.run_forever())
    await asyncio.wait_for(executed.wait(), timeout=3)
    task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await task


async def test_worker_requeues_when_execution_raises() -> None:
    queue = StubQueue(42)

    async def execute(run_id: int) -> None:
        raise RuntimeError("worker crash")

    worker = RedisRunWorker(queue, execute, claim_timeout_seconds=1)  # type: ignore[arg-type]

    with pytest.raises(RuntimeError, match="worker crash"):
        await worker.process_once()
    assert queue.run_id == 42
