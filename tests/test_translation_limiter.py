import asyncio

from subforge.translate.limiter import TranslationRequestLimiter


async def test_translation_request_limiter_caps_concurrent_requests(tmp_path):
    limiter = TranslationRequestLimiter(tmp_path / "slots", limit=2)
    active = 0
    peak = 0
    entered = asyncio.Event()

    async def request():
        nonlocal active, peak
        async with limiter.slot():
            active += 1
            peak = max(peak, active)
            if peak == 2:
                entered.set()
            await asyncio.sleep(0.03)
            active -= 1

    tasks = [asyncio.create_task(request()) for _ in range(6)]
    await asyncio.wait_for(entered.wait(), timeout=1)
    await asyncio.gather(*tasks)

    assert peak == 2


async def test_translation_request_limiter_can_be_disabled(tmp_path):
    limiter = TranslationRequestLimiter(None, limit=0)

    async with limiter.slot():
        pass
