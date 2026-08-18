"""
wwr.py — We Work Remotely RSS feed scraper (fallback source).

SOURCE DETAILS:
- URL: https://weworkremotely.com/categories/remote-jobs.rss
- Format: Standard RSS 2.0 XML feed
- Rate limiting: Minimal — it's a static RSS feed
- Auth: None required

PARSING APPROACH:
Uses the `feedparser` library, which handles RSS/Atom format variations,
malformed XML, and encoding issues gracefully. Field mappings are in
config.WWR_FIELD_MAP.

WHY THIS IS THE FALLBACK:
WWR's RSS feed is simple, reliable, and rarely blocks. It's the "safe"
source — when RemoteOK's circuit breaker trips, we fall back here and
keep the pipeline producing data. The trade-off is less detailed data
(RSS entries have fewer fields than RemoteOK's JSON).
"""

import feedparser
import structlog
from pydantic import ValidationError

from src import config
from src.models import JobListing
from src.scraper.base import BaseScraper

log = structlog.get_logger()


class WWRScraper(BaseScraper):
    """Scraper for the We Work Remotely RSS feed."""

    @property
    def name(self) -> str:
        return "wwr"

    @property
    def url(self) -> str:
        return config.WWR_RSS_URL

    def _extract_company_from_title(self, title: str) -> tuple[str, str]:
        """
        WWR titles are typically formatted as "Company: Job Title".
        Split on the first colon to extract both.

        If there's no colon, use the full title as both (better than empty).
        """
        if ":" in title:
            company, _, job_title = title.partition(":")
            return company.strip(), job_title.strip()
        return title.strip(), title.strip()

    def parse(self, raw: bytes) -> list[JobListing]:
        """
        Parse WWR's RSS feed into JobListing objects.

        feedparser handles the XML parsing. We map its normalized entry
        attributes to our JobListing schema.
        """
        feed = feedparser.parse(raw)

        if feed.bozo and not feed.entries:
            # bozo=True means feedparser encountered a problem. If there are
            # still entries, the feed is partially valid — use what we can.
            # If there are NO entries, the feed is truly broken.
            error_msg = str(feed.bozo_exception) if feed.bozo_exception else "Unknown RSS parse error"
            log.error("wwr_rss_parse_failed", error=error_msg)
            raise ValueError(f"RSS feed parse failed: {error_msg}")

        field_map = config.WWR_FIELD_MAP
        listings = []
        parse_errors = 0

        for entry in feed.entries:
            try:
                raw_title = getattr(entry, field_map["title"], "")

                # WWR puts "Company: Job Title" in the title field.
                # The author field sometimes has the company too, but
                # the title split is more reliable.
                company, job_title = self._extract_company_from_title(raw_title)

                url = getattr(entry, field_map["url"], "")

                # Generate a deterministic ID from the URL since RSS
                # entries don't have numeric IDs
                listing_id = self.make_id("wwr", url)

                # Extract tags from RSS categories if available
                tags = [tag.term for tag in getattr(entry, "tags", [])]

                listing = JobListing(
                    id=listing_id,
                    title=job_title,
                    company=company,
                    url=url,
                    location="Remote",  # WWR is exclusively remote jobs
                    tags=tags,
                    source=self.name,
                    raw={
                        "title": raw_title,
                        "link": url,
                        "summary": getattr(entry, field_map.get("summary", "summary"), ""),
                    },
                )
                listings.append(listing)

            except (ValidationError, ValueError) as e:
                parse_errors += 1
                log.warning(
                    "wwr_parse_entry_failed",
                    entry_title=getattr(entry, "title", "unknown"),
                    error=str(e),
                )

        log.info(
            "wwr_parse_complete",
            total_entries=len(feed.entries),
            parsed_ok=len(listings),
            parse_errors=parse_errors,
        )

        return listings
