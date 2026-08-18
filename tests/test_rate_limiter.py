import pytest

from src.resilience.rate_limiter import RateLimiter


@pytest.mark.asyncio
async def test_full_bucket_acquires_without_wait_when_jitter_disabled():
    limiter = RateLimiter(max_tokens=2, refill_seconds=60, jitter_max=0)

    delay = await limiter.acquire()

    assert delay == 0
    assert limiter._tokens == 1


@pytest.mark.asyncio
async def test_empty_bucket_waits_for_refill():
    limiter = RateLimiter(max_tokens=1, refill_seconds=0.01, jitter_max=0)
    await limiter.acquire()

    delay = await limiter.acquire()

    assert delay > 0
    assert limiter._tokens >= 0


@pytest.mark.asyncio
async def test_jitter_is_included_in_returned_delay(monkeypatch):
    limiter = RateLimiter(max_tokens=1, refill_seconds=60, jitter_max=2)
    monkeypatch.setattr(
        "src.resilience.rate_limiter.random.uniform", lambda _a, _b: 1.25
    )

    delay = await limiter.acquire()

    assert delay == 1.25
