"""
rate_limiter.py — Token-bucket rate limiter with jitter.

WHY NOT just time.sleep(2)?
A fixed sleep between requests is one of the easiest bot fingerprints.
Real users don't click links at exactly 2.000-second intervals. A rate
limiter with jitter produces variable delays that look more like human
browsing patterns.

HOW IT WORKS:
- The bucket starts full (max_tokens tokens).
- Each request consumes one token.
- Tokens refill at a fixed rate (one every `refill_seconds`).
- Before each request, we wait until a token is available, PLUS a random
  jitter between 0 and `jitter_max` seconds.
- The jitter is uniform random, not gaussian — we want a flat distribution
  of request timings, not clustering around the mean.
"""

import asyncio
import random
import time

import structlog

from src import config

log = structlog.get_logger()


class RateLimiter:
    """
    Async token-bucket rate limiter with configurable jitter.

    Usage:
        limiter = RateLimiter()
        await limiter.acquire()  # blocks until a token is available + jitter
        response = await client.get(url)
    """

    def __init__(
        self,
        max_tokens: int = config.RATE_LIMIT_MAX_TOKENS,
        refill_seconds: float = config.RATE_LIMIT_REFILL_SECONDS,
        jitter_max: float = config.RATE_LIMIT_JITTER_MAX,
    ):
        self.max_tokens = max_tokens
        self.refill_seconds = refill_seconds
        self.jitter_max = jitter_max

        # Start with a full bucket
        self._tokens = float(max_tokens)
        self._last_refill = time.monotonic()
        # Lock to prevent race conditions in async context
        self._lock = asyncio.Lock()

    def _refill(self) -> None:
        """Add tokens based on elapsed time since last refill."""
        now = time.monotonic()
        elapsed = now - self._last_refill
        # How many tokens have accumulated since last check?
        new_tokens = elapsed / self.refill_seconds
        self._tokens = min(self.max_tokens, self._tokens + new_tokens)
        self._last_refill = now

    async def acquire(self) -> float:
        """
        Wait until a token is available, then consume it.

        Returns the total delay (wait + jitter) in seconds, for logging.
        """
        total_delay = 0.0

        async with self._lock:
            self._refill()

            if self._tokens < 1.0:
                # No tokens available — calculate how long to wait for one
                deficit = 1.0 - self._tokens
                wait_time = deficit * self.refill_seconds
                log.debug(
                    "rate_limiter_waiting",
                    wait_seconds=round(wait_time, 2),
                    tokens_available=round(self._tokens, 2),
                )
                await asyncio.sleep(wait_time)
                total_delay += wait_time
                self._refill()

            # Consume one token
            self._tokens -= 1.0

        # Add jitter OUTSIDE the lock — don't hold the lock while sleeping
        jitter = random.uniform(0, self.jitter_max)
        await asyncio.sleep(jitter)
        total_delay += jitter

        log.debug(
            "rate_limiter_acquired",
            total_delay=round(total_delay, 2),
            jitter=round(jitter, 2),
            tokens_remaining=round(self._tokens, 2),
        )

        return total_delay
