from __future__ import annotations

from jmi_core.schema import JobSource
from jmi_core.settings import Settings
from jmi_scrapers.honeypot import HoneypotScraper

SAMPLE_RECORD = {
    "id": 12345,
    "title": "Analytics Engineer",
    "company": {"name": "Acme BV"},
    "location": "Amsterdam",
    "remote": True,
    "salary_min": 60000,
    "salary_max": 75000,
    "salary_currency": "EUR",
    "employment_type": "full_time",
    "seniority": "mid",
    "description": "We sponsor visas and offer relocation. We use dbt + Snowflake.",
    "url": "https://honeypot.io/jobs/12345",
}


def _scraper() -> HoneypotScraper:
    return HoneypotScraper(Settings(scrapfly_key="dummy"), run_id="run-1")


def test_parse_record_maps_core_fields():
    posting = _scraper()._parse_record(SAMPLE_RECORD)
    assert posting is not None
    assert posting.source is JobSource.HONEYPOT
    assert posting.source_job_id == "12345"
    assert posting.company_name == "Acme BV"
    assert posting.country_code == "NL"  # default_country
    assert posting.is_remote_raw is True
    assert posting.salary_raw == "EUR 60000-75000"
    assert posting.ingestion_run_id == "run-1"
    assert posting.content_hash  # computed
    # cheap language detection ran on the English description
    assert posting.detected_language == "en"


def test_parse_record_skips_without_id_or_title():
    s = _scraper()
    assert s._parse_record({"title": "x"}) is None
    assert s._parse_record({"id": 1}) is None


def test_records_envelope_variants():
    assert HoneypotScraper._records([{"id": 1}]) == [{"id": 1}]
    assert HoneypotScraper._records({"jobs": [{"id": 2}]}) == [{"id": 2}]
    assert HoneypotScraper._records({"nope": 1}) == []
