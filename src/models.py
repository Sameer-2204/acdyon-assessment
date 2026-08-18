"""
models.py — The data contract for the entire pipeline.

Every scraper, regardless of source, must produce `JobListing` objects.
Pydantic validates the data at parse time — if a source changes its schema
and we get garbage, this catches it as a ValidationError with a clear message
instead of silently passing malformed data downstream.

This is the single most important defense against "markup drift" — the source
changes, our parser produces wrong data, and we don't notice for days.
"""

from datetime import datetime, timezone
from typing import Optional

from pydantic import BaseModel, Field, field_validator, HttpUrl


class JobListing(BaseModel):
    """
    Normalized job listing that all scrapers must produce.

    Fields are deliberately minimal — only what we can reliably extract
    from both RemoteOK (JSON) and WWR (RSS). Adding optional fields is
    fine; making a field required means BOTH sources must provide it.
    """

    # Unique ID from the source (e.g., RemoteOK's numeric ID, or a hash of the URL)
    id: str = Field(description="Unique identifier from the source")

    title: str = Field(description="Job title / position name")
    company: str = Field(description="Company name")
    url: str = Field(description="Direct link to the job listing")

    # Optional fields — not all sources provide these
    location: Optional[str] = Field(
        default=None, description="Location (often 'Remote' or a region)"
    )
    tags: list[str] = Field(
        default_factory=list, description="Tags/categories from the source"
    )

    # Metadata
    source: str = Field(description="Which scraper produced this (e.g., 'remoteok', 'wwr')")
    scraped_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="When this listing was scraped (UTC)",
    )

    # Keep the raw payload for debugging. If something looks wrong in the
    # normalized data, you can inspect what the source actually returned.
    raw: Optional[dict] = Field(
        default=None,
        description="Original payload from the source, for debugging",
        exclude=True,  # Don't include in JSON serialization by default
    )

    @field_validator("title", "company")
    @classmethod
    def must_not_be_empty(cls, v: str, info) -> str:
        """Reject listings with blank titles or company names.
        These are almost always parsing errors, not real listings."""
        stripped = v.strip()
        if not stripped:
            raise ValueError(f"{info.field_name} must not be empty")
        return stripped

    @field_validator("url")
    @classmethod
    def must_be_valid_url(cls, v: str) -> str:
        """Basic URL validation — must start with http(s)."""
        if not v.startswith(("http://", "https://")):
            raise ValueError(f"Invalid URL: {v}")
        return v


class ScrapeResult(BaseModel):
    """
    Result of a single scrape attempt. Wraps the listings plus metadata
    about what happened — how many succeeded, failed, were skipped.

    This gives the pipeline structured information to decide whether the
    source is healthy or degrading.
    """

    source: str = Field(description="Source name")
    success: bool = Field(description="Whether the scrape completed without critical errors")
    listings: list[JobListing] = Field(default_factory=list)
    total_raw: int = Field(default=0, description="Total items in the raw response")
    parsed_ok: int = Field(default=0, description="Items that parsed + validated successfully")
    parse_errors: int = Field(default=0, description="Items that failed validation")
    error_message: Optional[str] = Field(
        default=None, description="Error message if the scrape failed entirely"
    )
    duration_seconds: float = Field(
        default=0.0, description="How long the scrape took"
    )
