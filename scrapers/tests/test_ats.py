"""Irish roles from employers' Greenhouse and Ashby boards."""

from __future__ import annotations

import pytest

from jmi_core.schema import JobSource
from jmi_core.settings import Settings
from jmi_scrapers.ats import AtsScraper, Employer, is_irish_location

GREENHOUSE = Employer("greenhouse", "intercom", "Intercom")
ASHBY = Employer("ashby", "wayflyer", "Wayflyer")


def _greenhouse(**overrides) -> dict:
    record = {
        "id": 8211426,
        "title": "Senior Data Scientist - Growth",
        "absolute_url": "https://job-boards.greenhouse.io/intercom/jobs/8211426",
        "location": {"name": "Dublin, Ireland"},
        "offices": [{"name": "Dublin, Ireland", "location": "Dublin, Ireland"}],
        "company_name": "Fin",
        "first_published": "2026-09-21T09:15:44-04:00",
        "content": "&lt;p&gt;We use &lt;strong&gt;dbt&lt;/strong&gt; and Snowflake.&lt;/p&gt;",
    }
    return {**record, **overrides}


def _ashby(**overrides) -> dict:
    record = {
        "id": "ee8e3e34",
        "title": "Analytics Engineer",
        "location": "Dublin",
        "secondaryLocations": [],
        "address": {"postalAddress": {"addressCountry": "Ireland"}},
        "isRemote": False,
        "publishedAt": "2026-07-17T14:01:12.096+00:00",
        "jobUrl": "https://jobs.ashbyhq.com/wayflyer/ee8e3e34",
        "applyUrl": "https://jobs.ashbyhq.com/wayflyer/ee8e3e34/application",
        "descriptionHtml": "<p>SQL, dbt, Looker.</p>",
        "employmentType": "FullTime",
        "compensation": {"compensationTierSummary": "€70K - €90K"},
    }
    return {**record, **overrides}


@pytest.mark.parametrize(
    ("locations", "irish"),
    [
        (("Dublin, Ireland",), True),
        (("Remote (IE)",), True),
        (("Cork",), True),
        (("London; Dublin",), True),  # the role can be held from Ireland
        (("Belfast, Northern Ireland",), False),  # the UK
        (("Belfast; Dublin",), True),
        (("Dublin, OH",), False),
        (("Dublin, California",), False),
        (("Remote - EMEA",), False),
        (("Amsterdam", None, "Dublin"), True),  # any of several fields
        ((None,), False),
    ],
)
def test_is_irish_location(locations, irish):
    assert is_irish_location(*locations) is irish


def test_greenhouse_parse():
    p = AtsScraper(Settings())._parse(GREENHOUSE, _greenhouse())
    assert p is not None
    assert p.source is JobSource.ATS
    assert p.source_job_id == "greenhouse:intercom:8211426"
    assert p.country_code == "IE"
    assert p.company_name == "Fin"  # the board's own current name wins
    assert p.description_raw == "<p>We use <strong>dbt</strong> and Snowflake.</p>"
    assert p.posted_at is not None and p.posted_at.year == 2026
    assert "content" not in p.raw_payload  # stored once, as description_raw


def test_ashby_parse():
    p = AtsScraper(Settings())._parse(ASHBY, _ashby())
    assert p is not None
    assert p.source_job_id == "ashby:wayflyer:ee8e3e34"
    assert p.country_code == "IE"
    assert p.company_name == "Wayflyer"
    assert p.apply_url.endswith("/application")
    assert p.salary_raw == "€70K - €90K"
    assert p.employment_type_raw == "FullTime"


def test_greenhouse_judges_the_postings_own_site_not_the_jobs_offices():
    # The Lisbon copy of a job that is also open in Dublin.
    lisbon = _greenhouse(location={"name": "Lisbon, Portugal"})
    assert AtsScraper(Settings())._parse(GREENHOUSE, lisbon) is None
    no_location = _greenhouse(location=None)
    assert AtsScraper(Settings())._parse(GREENHOUSE, no_location) is not None


def test_ashby_reads_secondary_locations():
    record = _ashby(location="London", address={}, secondaryLocations=[{"location": "Dublin"}])
    assert AtsScraper(Settings())._parse(ASHBY, record) is not None


@pytest.mark.parametrize(
    ("employer", "record"),
    [
        (GREENHOUSE, _greenhouse(title="Account Executive, Enterprise (German)")),
        (GREENHOUSE, _greenhouse(location={"name": "Amsterdam"}, offices=[])),
        (GREENHOUSE, _greenhouse(absolute_url=None)),
        (ASHBY, _ashby(title="Business Development Representative")),
        (ASHBY, _ashby(location="Berlin", address={})),
    ],
)
def test_off_role_non_irish_and_incomplete_postings_are_dropped(employer, record):
    assert AtsScraper(Settings())._parse(employer, record) is None


class _FakeHttp:
    def __init__(self, boards: dict[str, dict]) -> None:
        self.boards = boards

    def get_json(self, url, *, params=None, headers=None):
        for board, payload in self.boards.items():
            if f"/{board}/" in url or url.endswith(f"/{board}"):
                return payload
        raise RuntimeError(f"404 for {url}")  # a company that left the ATS


def test_scrape_survives_a_missing_board_and_respects_limit():
    gone = Employer("greenhouse", "left-greenhouse", "Gone")
    scraper = AtsScraper(Settings(), employers=(gone, GREENHOUSE, ASHBY))
    scraper._http = _FakeHttp(
        {
            "intercom": {"jobs": [_greenhouse(id=i) for i in range(1, 4)]},
            "wayflyer": {"jobs": [_ashby()]},
        }
    )
    assert len(list(scraper.scrape(10))) == 4  # the missing board is skipped
    assert len(list(scraper.scrape(2))) == 2


def test_scrape_keeps_one_copy_of_a_job_posted_per_site():
    scraper = AtsScraper(Settings(), employers=(GREENHOUSE,))
    copies = [
        _greenhouse(id=1, internal_job_id=77, location={"name": "Ireland"}),
        _greenhouse(id=2, internal_job_id=77, location={"name": "Cork, Ireland; Dublin, Ireland"}),
        _greenhouse(id=3, internal_job_id=78),
    ]
    scraper._http = _FakeHttp({"intercom": {"jobs": copies}})
    assert [p.source_job_id for p in scraper.scrape(10)] == [
        "greenhouse:intercom:1",
        "greenhouse:intercom:3",
    ]
