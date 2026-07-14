from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

import jmi_core
from jmi_core.schema import (
    EmploymentType,
    JobEnrichment,
    JobPosting,
    JobSource,
    RemotePolicy,
    Seniority,
    VisaSponsorship,
    VisaSponsorshipStatus,
    compute_content_hash,
)


def _posting(**overrides) -> JobPosting:
    base = {
        "source": JobSource.HONEYPOT,
        "source_job_id": "hp-1",
        "source_url": "https://honeypot.io/jobs/1",
        "scraped_at": datetime(2026, 6, 26, 8, 0, tzinfo=UTC),
        "title": "Analytics Engineer",
        "company_name": "Acme BV",
        "description_raw": "We sponsor visas and offer relocation to NL.",
        "salary_raw": "€60.000 - €75.000",
        "schema_version": jmi_core.SCHEMA_VERSION,
    }
    base.update(overrides)
    return JobPosting(**base)


def test_content_hash_is_deterministic_and_matches_standalone():
    p = _posting()
    again = compute_content_hash(
        source=p.source,
        source_job_id=p.source_job_id,
        title=p.title,
        company_name=p.company_name,
        location_raw=p.location_raw,
        salary_raw=p.salary_raw,
        description_raw=p.description_raw,
    )
    assert p.content_hash == again
    assert "content_hash" in p.model_dump()


def test_content_hash_changes_with_content():
    assert _posting().content_hash != _posting(title="Senior Analytics Engineer").content_hash


def test_naive_datetime_rejected():
    with pytest.raises(ValidationError):
        _posting(scraped_at=datetime(2026, 6, 26, 8, 0))  # no tzinfo


def test_unknown_field_rejected():
    with pytest.raises(ValidationError):
        _posting(bogus=1)


def test_enrichment_visa_range_validation():
    with pytest.raises(ValidationError):
        VisaSponsorship(status=VisaSponsorshipStatus.UNCLEAR, confidence=1.5)


def test_enrichment_roundtrip():
    p = _posting()
    e = JobEnrichment(
        content_hash=p.content_hash,
        source=p.source,
        source_job_id=p.source_job_id,
        enriched_at=datetime(2026, 6, 26, 8, 5, tzinfo=UTC),
        model="claude-haiku-4-5",
        prompt_version="enrich/v1",
        schema_version=jmi_core.SCHEMA_VERSION,
        seniority=Seniority.MID,
        employment_type=EmploymentType.FULL_TIME,
        remote_policy=RemotePolicy.HYBRID,
        technologies=["dbt", "snowflake"],
        visa=VisaSponsorship(status=VisaSponsorshipStatus.EXPLICIT_YES, confidence=0.95),
    )
    assert e.visa.status is VisaSponsorshipStatus.EXPLICIT_YES
    assert e.model_dump()["technologies"] == ["dbt", "snowflake"]
