from __future__ import annotations

import pytest

from jmi_core.schema import JobSource
from jmi_core.settings import Settings
from jmi_scrapers.free_apis import (
    AdzunaScraper,
    ArbeitnowScraper,
    RemoteOkScraper,
    RemotiveScraper,
)


def _s() -> Settings:
    return Settings()


def test_remotive_parse():
    rec = {
        "id": 1736522,
        "url": "https://remotive.com/remote-jobs/1736522",
        "title": "Senior Data Engineer",
        "company_name": "Acme",
        "candidate_required_location": "Europe",
        "job_type": "full_time",
        "salary": "€70k-90k",
        "publication_date": "2026-06-20T10:00:00",
        "description": "<p>We sponsor visas. dbt + Snowflake.</p>",
    }
    p = RemotiveScraper(_s())._parse(rec)
    assert p is not None
    assert p.source is JobSource.REMOTIVE
    assert p.source_job_id == "1736522"
    assert p.is_remote_raw is True
    assert p.posted_at.year == 2026


def test_arbeitnow_parse_unix_ts():
    rec = {
        "slug": "data-engineer-acme-berlin",
        "title": "Data Engineer",
        "company_name": "Acme GmbH",
        "description": "<p>We offer visa sponsorship and relocation to Berlin.</p>",
        "remote": True,
        "url": "https://www.arbeitnow.com/jobs/data-engineer-acme-berlin",
        "location": "Berlin",
        "job_types": ["full_time"],
        "created_at": 1718870400,
    }
    p = ArbeitnowScraper(_s())._parse(rec)
    assert p is not None
    assert p.source is JobSource.ARBEITNOW
    assert p.source_job_id == "data-engineer-acme-berlin"
    assert p.is_remote_raw is True
    assert p.posted_at is not None and p.posted_at.year == 2024


def test_remoteok_parse_and_salary():
    rec = {
        "id": "98765",
        "position": "Analytics Engineer",
        "company": "Globex",
        "location": "Worldwide",
        "tags": ["python", "dbt", "sql"],
        "description": "<p>Remote analytics engineer.</p>",
        "url": "https://remoteok.com/remote-jobs/98765",
        "date": "2026-06-21T08:00:00+00:00",
        "salary_min": 90000,
        "salary_max": 120000,
    }
    p = RemoteOkScraper(_s())._parse(rec)
    assert p is not None
    assert p.salary_raw == "USD 90000-120000"
    assert p.employment_type_raw == "python, dbt, sql"


def test_parsers_skip_incomplete():
    assert RemotiveScraper(_s())._parse({"id": 1}) is None
    assert ArbeitnowScraper(_s())._parse({"title": "x"}) is None
    assert RemoteOkScraper(_s())._parse({"legal": "notice"}) is None


def test_adzuna_parse_sets_country():
    rec = {
        "id": "555",
        "title": "Data Engineer",
        "company": {"display_name": "Acme NL"},
        "location": {"display_name": "Amsterdam, Noord-Holland"},
        "description": "We sponsor work visas.",
        "redirect_url": "https://www.adzuna.nl/details/555",
        "created": "2026-06-19T09:00:00Z",
        "salary_min": 60000.0,
        "salary_max": 80000.0,
        "contract_time": "full_time",
    }
    p = AdzunaScraper(_s(), country="nl")._parse(rec)
    assert p is not None
    assert p.country_code == "NL"
    assert p.salary_raw == "60000-80000"


class _FakeAdzunaHttp:
    """Fake HttpSession: one page of ``per_page`` distinct jobs per (what, page)."""

    def __init__(self, per_page: int = 50) -> None:
        self.per_page = per_page
        self.calls: list[tuple[str, int]] = []

    def get_json(self, url, *, params=None, headers=None):
        what, page = params["what"], int(url.rsplit("/", 1)[-1])
        self.calls.append((what, page))
        if page > 1:  # exactly one page of results per query
            return {"results": []}
        return {
            "results": [
                {
                    "id": f"{what}-{i}",
                    "title": what,
                    "company": {"display_name": "Acme NL"},
                    "location": {"display_name": "Amsterdam"},
                    "redirect_url": f"https://www.adzuna.nl/details/{what}-{i}",
                }
                for i in range(self.per_page)
            ]
        }


def test_adzuna_scrape_sweeps_queries_dedups_and_respects_limit():
    settings = _s()
    settings.adzuna_app_id, settings.adzuna_app_key = "id", "key"
    scraper = AdzunaScraper(settings, country="nl", whats=["data engineer", "data analyst"])
    scraper._http = _FakeAdzunaHttp(per_page=50)

    postings = list(scraper.scrape(10))

    assert len(postings) == 10  # respects the overall limit
    assert len({p.source_job_id for p in postings}) == 10  # no duplicates
    # spread across both queries rather than draining the first one
    whats = {p.title for p in postings}
    assert whats == {"data engineer", "data analyst"}


def test_adzuna_scrape_requires_credentials():
    settings = _s()
    settings.adzuna_app_id = settings.adzuna_app_key = None
    with pytest.raises(RuntimeError, match="ADZUNA_APP_ID"):
        list(AdzunaScraper(settings, country="nl").scrape(10))
