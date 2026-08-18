from unittest.mock import Mock

import pytest
import respx

from src import config
from src.models import JobListing, ScrapeResult
from src.pipeline import Pipeline
from src.resilience.circuit_breaker import CircuitBreaker, CircuitState
from src.resilience.rate_limiter import RateLimiter
from src.scraper.remoteok import RemoteOKScraper


class FakeCircuitBreaker:
    def __init__(self, name: str):
        self.name = name

    def get_status(self):
        return {"source": self.name, "state": "closed"}


class FakeScraper:
    def __init__(self, name: str, result: ScrapeResult):
        self.name = name
        self.result = result
        self.calls = 0
        self.circuit_breaker = FakeCircuitBreaker(name)

    async def scrape(self):
        self.calls += 1
        return self.result


class FakeRegistry:
    def __init__(self, sources):
        self.sources = sources

    def get_sources(self):
        return self.sources


def _listing(source="remoteok"):
    return JobListing(
        id="1",
        title="Engineer",
        company="Acme",
        url="https://example.com/jobs/1",
        source=source,
    )


@pytest.mark.asyncio
async def test_pipeline_uses_primary_without_calling_fallback():
    primary = FakeScraper(
        "remoteok", ScrapeResult(source="remoteok", success=True, listings=[_listing()])
    )
    fallback = FakeScraper(
        "wwr", ScrapeResult(source="wwr", success=True, listings=[_listing("wwr")])
    )
    pipeline = Pipeline(FakeRegistry([primary, fallback]))
    pipeline._save_results = Mock()

    result = await pipeline.run_once()

    assert result is primary.result
    assert primary.calls == 1
    assert fallback.calls == 0
    assert pipeline.successful_cycles == 1
    pipeline._save_results.assert_called_once_with(primary.result)


@pytest.mark.asyncio
async def test_pipeline_falls_back_after_primary_failure():
    primary = FakeScraper(
        "remoteok", ScrapeResult(source="remoteok", success=False, error_message="HTTP 403")
    )
    fallback = FakeScraper(
        "wwr", ScrapeResult(source="wwr", success=True, listings=[_listing("wwr")])
    )
    pipeline = Pipeline(FakeRegistry([primary, fallback]))
    pipeline._save_results = Mock()

    result = await pipeline.run_once()

    assert result is fallback.result
    assert (primary.calls, fallback.calls) == (1, 1)
    assert pipeline.fallback_activations == 1
    assert pipeline.get_status()["pipeline"]["fallback_activations"] == 1


@pytest.mark.asyncio
async def test_http_403_opens_primary_circuit_and_uses_fallback():
    primary = RemoteOKScraper(
        rate_limiter=RateLimiter(max_tokens=1, refill_seconds=60, jitter_max=0),
        circuit_breaker=CircuitBreaker(name="remoteok", failure_threshold=1),
    )
    fallback = FakeScraper(
        "wwr", ScrapeResult(source="wwr", success=True, listings=[_listing("wwr")])
    )
    pipeline = Pipeline(FakeRegistry([primary, fallback]))
    pipeline._save_results = Mock()

    try:
        with respx.mock(assert_all_called=True) as router:
            router.get(config.REMOTEOK_API_URL).respond(403)
            result = await pipeline.run_once()

        assert result is fallback.result
        assert primary.circuit_breaker.state is CircuitState.OPEN
        assert pipeline.fallback_activations == 1
    finally:
        await primary.close()


@pytest.mark.asyncio
async def test_pipeline_records_a_failed_cycle_when_every_source_fails():
    pipeline = Pipeline(
        FakeRegistry([
            FakeScraper("remoteok", ScrapeResult(source="remoteok", success=False)),
            FakeScraper("wwr", ScrapeResult(source="wwr", success=False)),
        ])
    )

    assert await pipeline.run_once() is None
    assert pipeline.failed_cycles == 1
