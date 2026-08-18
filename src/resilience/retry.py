"""
retry.py — Retry wrapper using tenacity with exponential backoff + jitter.

WHY TENACITY OVER HAND-ROLLED RETRY LOOPS:
Hand-rolled retry loops are easy to write but tricky to get right:
- Do you reset the backoff on partial success?
- Do you jitter the wait or just double it?
- Do you retry on timeouts but not on 403s?

Tenacity handles all of this declaratively. The retry policy reads like
a specification, not imperative code. And in the interview, you can point
to each parameter and explain what it does.

WHAT WE RETRY vs WHAT WE DON'T:
- RETRY: 429 (rate limited), 5xx (server error), connection errors, timeouts
- DON'T RETRY: 403 (blocked — report to circuit breaker), 404 (not found),
  4xx client errors (our problem, not transient), validation errors

The distinction matters: retrying a 403 means hammering a source that's
actively blocking us, which makes things worse. A 429 means "slow down",
which backoff naturally handles.
"""

import httpx
from tenacity import (
    retry,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential_jitter,
)

from src import config


def _is_retryable(exc: BaseException) -> bool:
    """
    Decide whether an exception warrants a retry.

    This is the core policy decision — which failures are transient
    (worth retrying) vs permanent (report and move on).
    """
    if isinstance(exc, httpx.TimeoutException):
        # Timeouts are usually transient — network hiccup, slow response
        return True

    if isinstance(exc, httpx.ConnectError):
        # Connection refused, DNS failure — often transient
        return True

    if isinstance(exc, httpx.HTTPStatusError):
        status = exc.response.status_code
        if status == 429:
            # Rate limited — the whole point of backoff
            return True
        if status >= 500:
            # Server error — usually transient
            return True
        # 403, 404, other 4xx — not retryable
        return False

    # Unknown exceptions — don't retry (fail fast, let circuit breaker handle it)
    return False


def with_retry(func):
    """
    Decorator that adds retry with exponential backoff + jitter.

    Backoff formula: wait = min(base * 2^attempt + random(0, base), max_wait)

    The 'full jitter' strategy (wait_exponential_jitter) is recommended by
    AWS's "Exponential Backoff and Jitter" paper — it spreads retries across
    time more effectively than simple exponential backoff alone.
    """
    return retry(
        retry=retry_if_exception(_is_retryable),
        stop=stop_after_attempt(config.RETRY_MAX_ATTEMPTS),
        wait=wait_exponential_jitter(
            initial=config.RETRY_BASE_WAIT_SECONDS,
            max=config.RETRY_MAX_WAIT_SECONDS,
            jitter=config.RETRY_BASE_WAIT_SECONDS,  # jitter range = base wait
        ),
        reraise=True,  # After exhausting retries, re-raise the last exception
    )(func)
