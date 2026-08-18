"""
base.py — Abstract base class for all scrapers.

THE ABSTRACTION:
Every source (RemoteOK, WWR, any future source) follows the same lifecycle:
1. fetch_raw() — make the HTTP request, get raw bytes
2. parse()     — transform raw bytes into JobListing objects
3. scrape()    — orchestrate fetch → parse → validate, return ScrapeResult

The base class handles the shared HTTP logic (rate limiting, retry, headers,
User-Agent rotation) so individual scrapers only need to implement parse().

WHY THIS LAYERING MATTERS:
- Adding a new source = one new file with one parse() method
- Changing the HTTP resilience behavior = change the base class, all sources benefit
- Testing a parser = call parse() with sample data, no HTTP needed
"""

import abc
import hashlib
import random
import time
from typing import Optional

import httpx
import structlog

from src import config
from src.models import JobListing, ScrapeResult
from src.resilience.circuit_breaker import CircuitBreaker
from src.resilience.rate_limiter import RateLimiter
from src.resilience.retry import with_retry

log = structlog.get_logger()


class BaseScraper(abc.ABC):
    """
    Abstract base class for job listing scrapers.

    Subclasses must implement:
    - name: str property (e.g., "remoteok", "wwr")
    - url: str property (the endpoint to fetch)
    - parse(raw: bytes) -> list[JobListing]
    """

    def __init__(
        self,
        rate_limiter: Optional[RateLimiter] = None,
        circuit_breaker: Optional[CircuitBreaker] = None,
    ):
        self.rate_limiter = rate_limiter or RateLimiter()
        self.circuit_breaker = circuit_breaker or CircuitBreaker(name=self.name)

        # Shared HTTP client with connection pooling and keep-alive.
        # Reusing a client across requests is both efficient and more
        # realistic (browsers reuse connections via keep-alive).
        self._client = httpx.AsyncClient(
            timeout=config.HTTP_TIMEOUT_SECONDS,
            follow_redirects=True,
        )

    @property
    @abc.abstractmethod
    def name(self) -> str:
        """Short identifier for this source (used in logs and results)."""
        ...

    @property
    @abc.abstractmethod
    def url(self) -> str:
        """The URL to fetch data from."""
        ...

    @abc.abstractmethod
    def parse(self, raw: bytes) -> list[JobListing]:
        """
        Parse raw response bytes into a list of JobListing objects.
        This is the ONLY method subclasses need to implement.

        Should NOT raise on individual parse failures — log and skip bad
        items, returning only the successfully parsed ones. Raise only on
        catastrophic failures (e.g., response is not JSON/XML at all).
        """
        ...

    def _get_headers(self) -> dict:
        """
        Build request headers with a rotated User-Agent.

        We rotate UAs randomly from a pool of real browser strings.
        Sending the same UA every time is a trivial bot fingerprint.
        """
        headers = dict(config.DEFAULT_HEADERS)
        headers["User-Agent"] = random.choice(config.USER_AGENTS)
        return headers

    async def fetch_raw(self) -> bytes:
        """
        Fetch raw data from the source URL with all resilience wrappers.

        This method:
        1. Waits for the rate limiter (with jitter)
        2. Sends the HTTP request with rotated headers
        3. Raises httpx.HTTPStatusError on non-2xx responses (for retry logic)
        4. Returns the raw response body as bytes

        The @with_retry decorator handles retries with exponential backoff.
        Failures that exhaust retries propagate to the caller (scrape()),
        which reports them to the circuit breaker.
        """

        @with_retry
        async def _do_fetch() -> bytes:
            # Rate limiter adds jitter — this is where anti-detection timing lives
            delay = await self.rate_limiter.acquire()

            headers = self._get_headers()
            log.info(
                "http_request_start",
                source=self.name,
                url=self.url,
                user_agent=headers.get("User-Agent", "")[:50] + "...",
                rate_limit_delay=round(delay, 2),
            )

            response = await self._client.get(self.url, headers=headers)

            # Raise on 4xx/5xx so the retry decorator can decide what to do
            response.raise_for_status()

            log.info(
                "http_request_complete",
                source=self.name,
                status=response.status_code,
                content_length=len(response.content),
            )

            return response.content

        return await _do_fetch()

    async def scrape(self) -> ScrapeResult:
        """
        Full scrape lifecycle: fetch → parse → validate → return result.

        This is what the pipeline calls. It handles all error cases and
        always returns a ScrapeResult (never raises).
        """
        start_time = time.monotonic()
        bound_log = log.bind(source=self.name)

        # Check circuit breaker FIRST — don't even try if the source is known-down
        if not self.circuit_breaker.allow_request():
            bound_log.warning("scrape_skipped_circuit_open")
            return ScrapeResult(
                source=self.name,
                success=False,
                error_message="Circuit breaker is open — source is degraded",
                duration_seconds=0.0,
            )

        try:
            # Step 1: Fetch raw data
            raw = await self.fetch_raw()

            # Step 2: Parse into JobListing objects
            listings = self.parse(raw)

            # Step 3: Record success with circuit breaker
            self.circuit_breaker.record_success()

            duration = time.monotonic() - start_time
            bound_log.info(
                "scrape_complete",
                listings_count=len(listings),
                duration=round(duration, 2),
            )

            return ScrapeResult(
                source=self.name,
                success=True,
                listings=listings,
                total_raw=len(listings),  # Will be overridden by subclasses if needed
                parsed_ok=len(listings),
                parse_errors=0,
                duration_seconds=round(duration, 2),
            )

        except Exception as e:
            # Record failure with circuit breaker
            self.circuit_breaker.record_failure()

            duration = time.monotonic() - start_time
            bound_log.error(
                "scrape_failed",
                error=str(e),
                error_type=type(e).__name__,
                duration=round(duration, 2),
            )

            return ScrapeResult(
                source=self.name,
                success=False,
                error_message=f"{type(e).__name__}: {e}",
                duration_seconds=round(duration, 2),
            )

    @staticmethod
    def make_id(source: str, unique_value: str) -> str:
        """
        Generate a deterministic ID from a source name + unique value.
        Used when the source doesn't provide its own ID (e.g., RSS feeds).
        """
        return hashlib.sha256(f"{source}:{unique_value}".encode()).hexdigest()[:12]

    async def close(self) -> None:
        """Close the HTTP client. Call on shutdown."""
        await self._client.aclose()
