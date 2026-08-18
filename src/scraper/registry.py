"""
registry.py — Source registry and fallback ordering.

This module maps source names to scraper instances and defines the
priority order for fallback. The pipeline asks the registry "give me
available sources in priority order" and tries them until one works.

WHY A REGISTRY:
- Adding a new source = register it here, write a parser, done
- The pipeline doesn't know or care which sources exist
- Fallback ordering is explicit and visible in one place
"""

from typing import Optional

import structlog

from src.resilience.circuit_breaker import CircuitBreaker
from src.resilience.rate_limiter import RateLimiter
from src.scraper.base import BaseScraper
from src.scraper.remoteok import RemoteOKScraper
from src.scraper.wwr import WWRScraper

log = structlog.get_logger()


class SourceRegistry:
    """
    Manages scraper instances and their fallback order.

    Sources are tried in order. The first one whose circuit breaker
    allows requests gets used. If it fails, the pipeline moves to
    the next one.
    """

    def __init__(self):
        # Each source gets its own rate limiter and circuit breaker.
        # We don't share rate limiters across sources — different sources
        # have different tolerances.
        self._sources: list[BaseScraper] = []

    def register(self, scraper: BaseScraper) -> None:
        """Add a source to the registry."""
        self._sources.append(scraper)
        log.info("source_registered", source=scraper.name, url=scraper.url)

    def get_sources(self) -> list[BaseScraper]:
        """Return all sources in priority order."""
        return list(self._sources)

    def get_source(self, name: str) -> Optional[BaseScraper]:
        """Get a specific source by name."""
        for source in self._sources:
            if source.name == name:
                return source
        return None

    async def close_all(self) -> None:
        """Close all HTTP clients. Call on shutdown."""
        for source in self._sources:
            await source.close()


def create_default_registry() -> SourceRegistry:
    """
    Create the standard registry with RemoteOK (primary) and WWR (fallback).

    This is the only place where source priority order is defined.
    RemoteOK is first because it has richer data. WWR is the fallback
    because it's more reliable but has less detail.
    """
    registry = SourceRegistry()

    # Primary: RemoteOK — richer data, but has rate limiting / Cloudflare
    remoteok_limiter = RateLimiter()
    remoteok_cb = CircuitBreaker(name="remoteok")
    registry.register(
        RemoteOKScraper(rate_limiter=remoteok_limiter, circuit_breaker=remoteok_cb)
    )

    # Fallback: WWR RSS — simpler data, but very reliable
    wwr_limiter = RateLimiter()
    wwr_cb = CircuitBreaker(name="wwr")
    registry.register(
        WWRScraper(rate_limiter=wwr_limiter, circuit_breaker=wwr_cb)
    )

    return registry
