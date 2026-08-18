from datetime import datetime

import pytest
from pydantic import ValidationError

from src.models import JobListing


def test_job_listing_accepts_valid_normalized_data():
    listing = JobListing(
        id="remoteok-1",
        title="  Python Engineer  ",
        company="  Acme Corp  ",
        url="https://example.com/jobs/1",
        source="remoteok",
    )

    assert listing.title == "Python Engineer"
    assert listing.company == "Acme Corp"
    assert listing.tags == []
    assert isinstance(listing.scraped_at, datetime)


@pytest.mark.parametrize(
    ("field", "value"),
    [("title", "  "), ("company", ""), ("url", "example.com/job")],
)
def test_job_listing_rejects_invalid_required_values(field, value):
    payload = {
        "id": "1",
        "title": "Engineer",
        "company": "Acme",
        "url": "https://example.com/job",
        "source": "test",
    }
    payload[field] = value

    with pytest.raises(ValidationError):
        JobListing(**payload)


def test_job_listing_excludes_raw_payload_from_json_dump():
    listing = JobListing(
        id="1",
        title="Engineer",
        company="Acme",
        url="https://example.com/job",
        source="test",
        raw={"upstream_field": "debug value"},
    )

    assert "raw" not in listing.model_dump(mode="json")
