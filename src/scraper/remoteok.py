"""
remoteok.py — RemoteOK JSON API scraper.

SOURCE DETAILS:
- URL: https://remoteok.com/api
- Format: JSON array. First element is a metadata object (skip it).
  Remaining elements are job objects with fields like "position", "company", etc.
- Rate limiting: Returns 403 if hit too fast. Has Cloudflare in front.
- Auth: None required (public endpoint).

PARSING APPROACH:
Field mappings are defined in config.REMOTEOK_FIELD_MAP. If RemoteOK renames
a field (e.g., "position" → "job_title"), you change the config, not this code.

Fields that fail Pydantic validation are logged and skipped — a single bad
listing doesn't crash the entire scrape.
"""

import json

import structlog
from pydantic import ValidationError

from src import config
from src.models import JobListing, ScrapeResult
from src.scraper.base import BaseScraper

log = structlog.get_logger()


class RemoteOKScraper(BaseScraper):
    """Scraper for the RemoteOK public JSON API."""

    @property
    def name(self) -> str:
        return "remoteok"

    @property
    def url(self) -> str:
        return config.REMOTEOK_API_URL

    def parse(self, raw: bytes) -> list[JobListing]:
        """
        Parse RemoteOK's JSON response into JobListing objects.

        The response is a JSON array where:
        - Index 0: metadata object (legal notice, etc.) — skip it
        - Index 1+: job listing objects

        Each job object has fields defined by REMOTEOK_FIELD_MAP in config.
        """
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as e:
            log.error("remoteok_json_parse_failed", error=str(e))
            raise  # Can't recover from invalid JSON — let scrape() handle it

        if not isinstance(data, list):
            log.error("remoteok_unexpected_format", type=type(data).__name__)
            raise ValueError(f"Expected JSON array, got {type(data).__name__}")

        # Skip the first element (metadata/legal notice)
        job_entries = data[1:] if len(data) > 1 else []

        field_map = config.REMOTEOK_FIELD_MAP
        listings = []
        parse_errors = 0

        for entry in job_entries:
            try:
                # Map RemoteOK's field names to our normalized model
                # using the config-driven field map
                listing = JobListing(
                    id=str(entry.get(field_map["id"], "")),
                    title=entry.get(field_map["title"], ""),
                    company=entry.get(field_map["company"], ""),
                    url=entry.get(field_map["url"], ""),
                    location=entry.get(field_map["location"]),
                    tags=entry.get(field_map["tags"], []) or [],
                    source=self.name,
                    raw=entry,
                )
                listings.append(listing)

            except (ValidationError, ValueError) as e:
                # Log the specific entry that failed, but keep going.
                # One bad listing shouldn't kill the entire scrape.
                parse_errors += 1
                log.warning(
                    "remoteok_parse_entry_failed",
                    entry_id=entry.get("id", "unknown"),
                    error=str(e),
                )

        log.info(
            "remoteok_parse_complete",
            total_entries=len(job_entries),
            parsed_ok=len(listings),
            parse_errors=parse_errors,
        )

        return listings
