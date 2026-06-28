from __future__ import annotations

from datetime import datetime, timezone

import pytest

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
)
from jmi_core.warehouse import Warehouse


@pytest.fixture
def wh(tmp_path):
    db = Warehouse(str(tmp_path / "test.duckdb"))
    db.init_schema()
    yield db
    db.close()


def _posting(job_id: str = "hp-1", *, title: str = "Analytics Engineer", scraped="2026-06-26T08:00:00+00:00") -> JobPosting:
    return JobPosting(
        source=JobSource.HONEYPOT,
        source_job_id=job_id,
        source_url=f"https://honeypot.io/jobs/{job_id}",
        scraped_at=datetime.fromisoformat(scraped),
        title=title,
        company_name="Acme BV",
        description_raw="We sponsor visas.",
        salary_raw="€60.000 - €75.000",
        country_code="NL",
        raw_payload={"id": job_id, "raw": True},
        schema_version=jmi_core.SCHEMA_VERSION,
    )


def test_init_schema_creates_tables(wh):
    schemas = {r["schema_name"] for r in wh.query("SELECT schema_name FROM information_schema.schemata")}
    assert {"raw", "staging", "marts"} <= schemas
    tables = {r["table_name"] for r in wh.query("SELECT table_name FROM information_schema.tables WHERE table_schema='raw'")}
    assert {"raw_job_postings", "raw_job_enrichment"} <= tables


def test_insert_and_count_postings(wh):
    inserted = wh.insert_postings([_posting("a"), _posting("b")])
    assert inserted == 2
    rows = wh.query("SELECT source, content_hash, raw_payload FROM raw.raw_job_postings ORDER BY source_job_id")
    assert len(rows) == 2
    assert rows[0]["source"] == "honeypot"
    assert rows[0]["content_hash"]  # computed field persisted


def test_append_only_snapshots(wh):
    p1 = _posting("a", scraped="2026-06-26T08:00:00+00:00")
    p2 = _posting("a", scraped="2026-06-27T08:00:00+00:00")  # same posting, next day
    wh.insert_postings([p1, p2])
    rows = wh.query("SELECT content_hash FROM raw.raw_job_postings WHERE source_job_id='a'")
    assert len(rows) == 2  # two observations
    assert rows[0]["content_hash"] == rows[1]["content_hash"]  # unchanged content => same hash


def test_fetch_postings_needing_enrichment_then_upsert(wh):
    p = _posting("a")
    wh.insert_postings([p])
    pending = wh.fetch_postings_needing_enrichment()
    assert len(pending) == 1
    assert pending[0]["content_hash"] == p.content_hash

    e = JobEnrichment(
        content_hash=p.content_hash,
        source=p.source,
        source_job_id=p.source_job_id,
        enriched_at=datetime(2026, 6, 26, 8, 5, tzinfo=timezone.utc),
        model="claude-haiku-4-5",
        prompt_version="enrich/v1",
        schema_version=jmi_core.SCHEMA_VERSION,
        seniority=Seniority.MID,
        employment_type=EmploymentType.FULL_TIME,
        remote_policy=RemotePolicy.REMOTE,
        technologies=["dbt", "duckdb"],
        visa=VisaSponsorship(
            status=VisaSponsorshipStatus.EXPLICIT_YES, confidence=0.9, evidence="We sponsor visas."
        ),
        input_tokens=1000,
        output_tokens=120,
        cost_usd=0.0016,
    )
    assert wh.upsert_enrichments([e]) == 1
    assert wh.fetch_postings_needing_enrichment() == []  # now enriched

    row = wh.query("SELECT visa_status, technologies FROM raw.raw_job_enrichment")[0]
    assert row["visa_status"] == "explicit_yes"
    assert list(row["technologies"]) == ["dbt", "duckdb"]


def test_enrichment_upsert_is_idempotent(wh):
    p = _posting("a")
    wh.insert_postings([p])
    e = JobEnrichment(
        content_hash=p.content_hash,
        source=p.source,
        source_job_id=p.source_job_id,
        enriched_at=datetime(2026, 6, 26, 8, 5, tzinfo=timezone.utc),
        model="claude-haiku-4-5",
        prompt_version="enrich/v1",
        schema_version=jmi_core.SCHEMA_VERSION,
        visa=VisaSponsorship(status=VisaSponsorshipStatus.UNCLEAR, confidence=0.2),
    )
    wh.upsert_enrichments([e])
    wh.upsert_enrichments([e])  # replace, not duplicate
    assert wh.query("SELECT count(*) AS n FROM raw.raw_job_enrichment")[0]["n"] == 1
