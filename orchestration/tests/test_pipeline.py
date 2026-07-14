"""Offline pipeline tests: fake scraper + fake classifier + local DuckDB.

Exercises the full ingest -> raw -> fetch-pending -> enrich -> upsert loop
without Prefect, Scrapfly, or Anthropic.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

import jmi_core
from jmi_core.schema import (
    JobEnrichment,
    JobPosting,
    JobSource,
    Seniority,
    VisaSponsorship,
    VisaSponsorshipStatus,
)
from jmi_core.settings import Settings
from jmi_core.warehouse import Warehouse
from jmi_flows.pipeline import enrich_pending, ingest_source


@pytest.fixture
def wh(tmp_path):
    db = Warehouse(str(tmp_path / "p.duckdb"))
    db.init_schema()
    yield db
    db.close()


class FakeScraper:
    def __init__(self, n: int):
        self.n = n

    def scrape(self, limit: int):
        for i in range(min(self.n, limit)):
            yield JobPosting(
                source=JobSource.HONEYPOT,
                source_job_id=f"hp-{i}",
                source_url=f"https://honeypot.io/jobs/{i}",
                scraped_at=datetime.now(UTC),
                title=f"Data Engineer {i}",
                company_name="Acme BV",
                description_raw="We sponsor visas. dbt + Snowflake.",
                country_code="NL",
                schema_version=jmi_core.SCHEMA_VERSION,
            )


class FakeClassifier:
    """Returns a deterministic enrichment for each pending row."""

    def classify_many(self, postings):
        for p in postings:
            yield JobEnrichment(
                content_hash=p["content_hash"],
                source=JobSource(p["source"]),
                source_job_id=p["source_job_id"],
                enriched_at=datetime.now(UTC),
                model="claude-haiku-4-5",
                prompt_version="enrich/v1",
                schema_version=jmi_core.SCHEMA_VERSION,
                seniority=Seniority.MID,
                technologies=["dbt"],
                visa=VisaSponsorship(status=VisaSponsorshipStatus.EXPLICIT_YES, confidence=0.9),
            )


def test_ingest_then_enrich_end_to_end(wh):
    inserted = ingest_source("honeypot", warehouse=wh, scraper=FakeScraper(3), limit=10)
    assert inserted == 3

    enriched = enrich_pending(
        settings=Settings(), warehouse=wh, classifier=FakeClassifier(), limit=10
    )
    assert enriched == 3
    assert wh.fetch_postings_needing_enrichment() == []

    rows = wh.query(
        "SELECT count(*) AS n FROM raw.raw_job_enrichment WHERE visa_status='explicit_yes'"
    )
    assert rows[0]["n"] == 3


def test_enrich_noop_when_nothing_pending(wh):
    assert enrich_pending(settings=Settings(), warehouse=wh, classifier=FakeClassifier()) == 0


def test_ingest_respects_limit(wh):
    assert ingest_source("honeypot", warehouse=wh, scraper=FakeScraper(100), limit=5) == 5
