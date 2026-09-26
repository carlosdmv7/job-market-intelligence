from __future__ import annotations

import pytest

from jmi_core.roles import is_target_role
from jmi_core.schema import JobSource
from jmi_core.settings import Settings
from jmi_scrapers.free_apis import (
    AdzunaScraper,
    ArbeitnowScraper,
    JobTechScraper,
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
    assert JobTechScraper(_s())._parse({"headline": "x"}) is None


def test_jobtech_parse():
    rec = {
        "id": "31276354",
        "headline": "Data Engineer till KTH",
        "webpage_url": "https://arbetsformedlingen.se/platsbanken/annonser/31276354",
        "publication_date": "2026-07-16T10:28:10",
        "application_deadline": "2026-08-15T23:59:59",
        "employer": {
            "name": "KUNGLIGA TEKNISKA HÖGSKOLAN",
            "url": "https://www.kth.se",
            "organization_number": "2021003054",
        },
        "workplace_address": {
            "municipality": "Stockholm",
            "region": "Stockholms län",
            "country_code": "199",
        },
        "description": {"text": "We build data pipelines with dbt and Airflow."},
        "application_details": {"url": "https://kth.varbi.com/what/apply"},
        "employment_type": {"label": "Vanlig anställning"},
        "salary_description": "Månadslön enligt avtal",
    }
    p = JobTechScraper(_s())._parse(rec)
    assert p is not None
    assert p.source is JobSource.JOBTECH
    assert p.source_job_id == "31276354"
    assert p.country_code == "SE"
    assert p.location_raw == "Stockholm, Stockholms län"
    assert str(p.apply_url) == "https://kth.varbi.com/what/apply"
    assert p.company_name == "KUNGLIGA TEKNISKA HÖGSKOLAN"
    assert p.posted_at is not None and p.posted_at.year == 2026
    assert p.valid_through is not None and p.valid_through.month == 8
    assert p.employment_type_raw == "Vanlig anställning"


class _FakeJobTechHttp:
    """Fake HttpSession honouring the API's ``limit`` param (as the real one does)."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    def get_json(self, url, *, params=None, headers=None):
        what = params["q"]
        self.calls.append(what)
        return {
            "hits": [
                {
                    "id": f"{what}-{i}",
                    "headline": what,
                    "webpage_url": f"https://arbetsformedlingen.se/platsbanken/annonser/{what}-{i}",
                    "employer": {"name": "Acme AB"},
                    "workplace_address": {"municipality": "Stockholm"},
                }
                for i in range(int(params["limit"]))
            ]
        }


def test_jobtech_scrape_sweeps_queries_dedups_and_respects_limit():
    scraper = JobTechScraper(_s(), whats=["data engineer", "data analyst"])
    scraper._http = _FakeJobTechHttp()

    postings = list(scraper.scrape(10))

    assert len(postings) == 10  # respects the overall limit
    assert len({p.source_job_id for p in postings}) == 10  # no duplicates
    assert all(p.country_code == "SE" for p in postings)
    # spread across both queries rather than draining the first one
    assert {p.title for p in postings} == {"data engineer", "data analyst"}


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


# --- the data-role filter on the unsearchable boards -------------------------
# Remotive, Arbeitnow and RemoteOK return their whole board, so the scope
# decision that DATA_ROLE_QUERIES expresses for Adzuna/JobTech has to be
# enforced here instead.


class _FakeBoardHttp:
    """Serves one page of records, whatever shape the caller asks for."""

    def __init__(self, payload: dict) -> None:
        self.payload = payload
        self.calls: list[dict] = []

    def get_json(self, url, *, params=None, headers=None):
        self.calls.append({"url": url, "params": params})
        return self.payload


@pytest.mark.parametrize(
    ("title", "kept"),
    [
        ("Senior Data Engineer", True),
        ("Analytics Engineer", True),
        ("Machine Learning Engineer", True),
        ("Senior BI Developer", True),
        ("AI Engineer (m/w/d)", True),
        ("Data Scientist", True),
        # An earlier pattern anchored only the front of each term and matched
        # "BI" inside "Bildung", re-admitting exactly the noise it removes.
        ("Werkstudent (m/w/d) Redaktion Bildung.Table", False),
        # "BI" is a whole word in "Bi-lingual"; the word is removed before matching.
        ("Sr. Key Account Executive (Bi-lingual) German", False),
        ("Bi-lingual Data Analyst (German)", True),
        ("Hotel Executive Assistant Manager", False),
        ("Steuerberater (m/w/d)", False),
        ("Senior Sales Executive", False),
        ("Transactional Financial Controller", False),
        (None, False),
    ],
)
def test_is_target_role(title, kept):
    assert is_target_role(title) is kept


def test_remotive_scrape_drops_off_role_postings():
    http = _FakeBoardHttp(
        {
            "jobs": [
                {"id": 1, "url": "u1", "title": "Data Engineer"},
                {"id": 2, "url": "u2", "title": "Hotel Manager"},
                {"id": 3, "url": "u3", "title": "Analytics Engineer"},
            ]
        }
    )
    scraper = RemotiveScraper(_s())
    scraper._http = http

    titles = [p.title for p in scraper.scrape(10)]

    assert titles == ["Data Engineer", "Analytics Engineer"]


def test_remoteok_scrape_drops_off_role_postings():
    http = _FakeBoardHttp(
        [
            {"id": 0, "legal": "disclaimer"},
            {"id": 1, "url": "u1", "position": "Senior Data Analyst"},
            {"id": 2, "url": "u2", "position": "Account Executive"},
        ]
    )
    scraper = RemoteOkScraper(_s())
    scraper._http = http

    titles = [p.title for p in scraper.scrape(10)]

    assert titles == ["Senior Data Analyst"]


def test_remoteok_double_encoded_text_is_repaired_before_the_role_filter():
    # Exactly as RemoteOK serves it: UTF-8 bytes decoded as Latin-1.
    garbled_location = "مسقط, عمان".encode().decode("latin-1")
    http = _FakeBoardHttp(
        [
            {"id": 0, "legal": "disclaimer"},
            {
                "id": 7,
                "url": "u7",
                "position": "Data Analyst Júnior".encode().decode("latin-1"),
                "company": "Café Lab",  # genuine accent, must survive untouched
                "location": garbled_location,
            },
        ]
    )
    scraper = RemoteOkScraper(_s())
    scraper._http = http

    (posting,) = list(scraper.scrape(10))

    assert posting.title == "Data Analyst Júnior"
    assert posting.location_raw == "مسقط, عمان"
    assert posting.company_name == "Café Lab"


def test_arbeitnow_scrape_drops_off_role_postings():
    http = _FakeBoardHttp(
        {
            "data": [
                {"slug": "a", "url": "u1", "title": "Data Platform Engineer"},
                {"slug": "b", "url": "u2", "title": "Steuerberater (m/w/d)"},
            ],
            "links": {"next": None},
        }
    )
    scraper = ArbeitnowScraper(_s())
    scraper._http = http

    titles = [p.title for p in scraper.scrape(10)]

    assert titles == ["Data Platform Engineer"]


def test_limit_counts_relevant_postings_not_records_scanned():
    # The point of the filter is that `limit` still means "this many usable
    # postings", so a board that is mostly noise must be read further.
    jobs = [{"id": i, "url": f"u{i}", "title": "Sales Executive"} for i in range(50)]
    jobs += [{"id": 100 + i, "url": f"v{i}", "title": "Data Engineer"} for i in range(3)]
    scraper = RemotiveScraper(_s())
    scraper._http = _FakeBoardHttp({"jobs": jobs})

    postings = list(scraper.scrape(3))

    assert len(postings) == 3
    assert all(p.title == "Data Engineer" for p in postings)
