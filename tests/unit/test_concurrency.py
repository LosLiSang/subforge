import asyncio

import pytest

from subforge.concurrency import (
    LOCAL,
    REMOTE,
    AdmissionGate,
    ConcurrencyPolicy,
    chunk_fanout,
    task_domain,
)


@pytest.mark.parametrize("kind, provider, processor, expected", [
    ("full_process", "local", None, LOCAL),
    ("full_process", None, None, LOCAL),
    ("full_process", "deepgram", None, REMOTE),
    ("full_process", "model", None, REMOTE),
    ("segment_reprocess", None, "whisper", LOCAL),
    ("segment_reprocess", None, None, LOCAL),
    ("segment_reprocess", "deepgram", "gemini", REMOTE),
])
def test_task_domain(kind, provider, processor, expected):
    assert task_domain(kind, asr_provider=provider, processor=processor) == expected


@pytest.mark.parametrize("chunks, requests, expected", [
    (10, 2, 2),
    (1, 8, 1),
    (0, 4, 1),
    (3, 3, 3),
])
def test_chunk_fanout_bounded_by_chunks_and_request_pool(chunks, requests, expected):
    assert chunk_fanout(chunks, requests) == expected


def test_policy_admission_limits_and_validation():
    policy = ConcurrencyPolicy(local_asr=2, remote_asr_tasks=1, remote_asr_requests=6, llm_requests=8)
    assert policy.admission_limit(LOCAL) == 2
    assert policy.admission_limit(REMOTE) == 1
    with pytest.raises(ValueError):
        policy.admission_limit("other")
    for field in ("local_asr", "remote_asr_tasks", "remote_asr_requests", "llm_requests"):
        with pytest.raises(ValueError):
            ConcurrencyPolicy(**{field: 0})


async def test_admission_gate_is_fifo_and_reads_limit_live():
    limit = {"value": 1}
    gate = AdmissionGate(lambda: limit["value"])
    order: list[int] = []

    await gate.acquire()  # 占满

    async def waiter(n):
        await gate.acquire()
        order.append(n)

    tasks = [asyncio.create_task(waiter(n)) for n in range(3)]
    await asyncio.sleep(0)
    assert gate.waiting == 3 and order == []

    limit["value"] = 3  # 调大容量后 wake 立即放行，且按入队顺序
    gate.wake()
    await asyncio.sleep(0)
    assert order == [0, 1]
    assert gate.active == 3

    gate.release()
    await asyncio.gather(*tasks)
    assert order == [0, 1, 2]


async def test_admission_gate_cancelled_waiter_does_not_leak_slot():
    gate = AdmissionGate(lambda: 1)
    await gate.acquire()
    pending = asyncio.create_task(gate.acquire())
    await asyncio.sleep(0)
    pending.cancel()
    with pytest.raises(asyncio.CancelledError):
        await pending
    gate.release()
    assert gate.active == 0 and gate.waiting == 0
