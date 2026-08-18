"""
pipeline.py — Scrape cycle orchestrator.

This is the "brain" of the system. It runs on a schedule, tries sources
in priority order, handles failover, and persists results.

THE FLOW:
1. For each source in priority order:
   a. Check if circuit breaker allows a request
   b. If yes: scrape, save results, STOP (don't hit fallback if primary works)
   c. If no: skip to next source (circuit breaker handles the "why")
2. If ALL sources fail: log critical alert, wait, try again next cycle
3. Sleep with jitter before the next cycle

KEY DESIGN CHOICE — "first success wins":
We stop after the first successful source. This is intentional:
- Saves request budget (don't hit WWR if RemoteOK works)
- Each source has its own rate limiter, so unnecessary requests waste tokens
- If we hit ALL sources every cycle, we look more like a bot (parallel scraping)
"""

import asyncio
import json
import os
import random
import time
from datetime import datetime, timezone
from pathlib import Path

import structlog

from src import config
from src.models import ScrapeResult
from src.scraper.registry import SourceRegistry

log = structlog.get_logger()


class Pipeline:
    """
    Orchestrates the scrape cycle: try sources in order, save results,
    handle failures, repeat on schedule.
    """

    def __init__(self, registry: SourceRegistry):
        self.registry = registry
        self._data_dir = Path(config.DATA_DIR)
        self._data_dir.mkdir(parents=True, exist_ok=True)

        # Track pipeline-level metrics
        self.total_cycles = 0
        self.successful_cycles = 0
        self.failed_cycles = 0
        self.fallback_activations = 0
        self.last_scrape_time: str | None = None
        self.last_scrape_source: str | None = None
        self.last_result: ScrapeResult | None = None

    async def run_once(self) -> ScrapeResult | None:
        """
        Run a single scrape cycle. Tries sources in priority order.

        Returns the ScrapeResult from the first successful source,
        or None if all sources failed.
        """
        self.total_cycles += 1
        cycle_log = log.bind(cycle=self.total_cycles)
        cycle_log.info("scrape_cycle_start")

        for source_index, source in enumerate(self.registry.get_sources()):
            result = await source.scrape()

            if result.success and result.listings:
                # Got data — save it and stop
                self._save_results(result)
                self.successful_cycles += 1
                if source_index > 0:
                    self.fallback_activations += 1
                self.last_scrape_time = datetime.now(timezone.utc).isoformat()
                self.last_scrape_source = result.source
                self.last_result = result

                cycle_log.info(
                    "scrape_cycle_complete",
                    source=result.source,
                    listings=len(result.listings),
                    duration=result.duration_seconds,
                )
                return result

            elif result.success and not result.listings:
                # Source responded OK but returned no data — unusual but not
                # a failure. Log and try next source.
                cycle_log.warning(
                    "scrape_empty_response",
                    source=result.source,
                )
                # Don't count as a circuit breaker failure — the source is
                # working, just empty. But do try the fallback.
                continue

            else:
                # Source failed — the scraper already reported to its circuit
                # breaker. Move to the next source.
                cycle_log.warning(
                    "scrape_source_failed",
                    source=result.source,
                    error=result.error_message,
                )
                continue

        # All sources failed
        self.failed_cycles += 1
        cycle_log.error(
            "scrape_cycle_all_sources_failed",
            sources_tried=[s.name for s in self.registry.get_sources()],
        )
        return None

    def _save_results(self, result: ScrapeResult) -> None:
        """
        Save scraped listings to a JSON file.

        Files are named by timestamp so we keep a history. In production
        you'd write to a database, but for this demo flat files are
        sufficient and easy to inspect.
        """
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        filename = f"{result.source}_{timestamp}.json"
        filepath = self._data_dir / filename

        # Also maintain a "latest.json" symlink/copy for the API endpoint
        latest_path = self._data_dir / "latest.json"

        data = {
            "source": result.source,
            "scraped_at": datetime.now(timezone.utc).isoformat(),
            "count": len(result.listings),
            "listings": [
                listing.model_dump(mode="json") for listing in result.listings
            ],
        }

        # Write timestamped file
        filepath.write_text(json.dumps(data, indent=2, default=str))

        # Write/overwrite latest.json for the API
        latest_path.write_text(json.dumps(data, indent=2, default=str))

        log.info(
            "results_saved",
            filepath=str(filepath),
            count=len(result.listings),
        )

    def get_latest_listings(self) -> dict:
        """
        Read the latest scraped data from disk.
        Returns the parsed JSON or an empty result if no data exists yet.
        """
        latest_path = self._data_dir / "latest.json"
        if latest_path.exists():
            return json.loads(latest_path.read_text())
        return {"source": None, "scraped_at": None, "count": 0, "listings": []}

    def get_status(self) -> dict:
        """Return pipeline status for the /status endpoint."""
        return {
            "pipeline": {
                "total_cycles": self.total_cycles,
                "successful_cycles": self.successful_cycles,
                "failed_cycles": self.failed_cycles,
                "fallback_activations": self.fallback_activations,
                "last_scrape_time": self.last_scrape_time,
                "last_scrape_source": self.last_scrape_source,
            },
            "sources": [
                source.circuit_breaker.get_status()
                for source in self.registry.get_sources()
            ],
        }

    async def run_loop(self) -> None:
        """
        Run the scrape cycle on a schedule forever.

        Each cycle is followed by a sleep with jitter:
          sleep = SCRAPE_INTERVAL + random(-JITTER, +JITTER)

        The jitter prevents the scraper from hitting sources at
        predictable, fixed intervals — another anti-detection measure.
        """
        log.info(
            "pipeline_loop_start",
            interval=config.SCRAPE_INTERVAL_SECONDS,
            jitter=config.SCRAPE_INTERVAL_JITTER,
        )

        while True:
            await self.run_once()

            # Sleep with jitter
            jitter = random.uniform(
                -config.SCRAPE_INTERVAL_JITTER,
                config.SCRAPE_INTERVAL_JITTER,
            )
            sleep_time = max(10, config.SCRAPE_INTERVAL_SECONDS + jitter)

            log.info(
                "pipeline_sleeping",
                sleep_seconds=round(sleep_time, 1),
                jitter=round(jitter, 1),
            )
            await asyncio.sleep(sleep_time)
