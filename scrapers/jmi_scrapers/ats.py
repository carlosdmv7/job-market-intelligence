"""Irish data roles, read from employers' own applicant-tracking systems.

No job board with an open API covers Ireland. Adzuna, the source for NL, DE and
ES, has no Irish site (``/jobs/ie`` is a 404); the EU's EURES search endpoint is
undocumented and gone; IrishJobs, Jobs.ie and Indeed have no API at all, and
scraping them would break their terms. What *is* open is the other end of the
pipe: Greenhouse and Ashby publish every customer's job board as public JSON,
no key, and a large share of Dublin's tech employers hire through one of them.

So this source is a **sample of employers, not the Irish market**. Where
Adzuna returns whatever the country's boards carry, this returns what 33
companies — mostly US tech with an EMEA hub in Dublin — have open. The app says
so wherever Ireland sits next to a market read whole.

How the list was drawn (Sep 2026): every employer whose board carried an Irish
posting *of any kind* — chosen for having an Irish office, not for having data
roles open that day, which would have picked the sample by the answer.

Only Irish postings are kept. The same boards list roles in the Netherlands
and Germany, but those markets are read whole from Adzuna; mixing a hand-picked
employer sample into them would change what they measure.
"""

from __future__ import annotations

import html
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal

from jmi_core.logging import get_logger
from jmi_core.roles import is_target_role
from jmi_core.schema import JobSource
from jmi_scrapers.base import BaseScraper, parse_iso_dt

if TYPE_CHECKING:
    from collections.abc import Iterator

    from jmi_core.schema import JobPosting

log = get_logger(__name__)


@dataclass(frozen=True)
class Employer:
    ats: Literal["greenhouse", "ashby"]
    board: str  # the company's token in the ATS's public URL
    name: str  # fallback when the payload carries no company name


EMPLOYERS: tuple[Employer, ...] = (
    *(
        Employer("greenhouse", board, name)
        for board, name in (
            ("airbnb", "Airbnb"),
            ("asana", "Asana"),
            ("coinbase", "Coinbase"),
            ("databricks", "Databricks"),
            ("datadog", "Datadog"),
            ("deliveroo", "Deliveroo"),
            ("dropbox", "Dropbox"),
            ("elastic", "Elastic"),
            ("fivetran", "Fivetran"),
            ("flipdish", "Flipdish"),
            ("gitlab", "GitLab"),
            ("hellofresh", "HelloFresh"),
            ("intercom", "Intercom"),
            ("klaviyo", "Klaviyo"),
            ("launchdarkly", "LaunchDarkly"),
            ("mongodb", "MongoDB"),
            ("newrelic", "New Relic"),
            ("okta", "Okta"),
            ("payoneer", "Payoneer"),
            ("pinterest", "Pinterest"),
            ("squarespace", "Squarespace"),
            ("stripe", "Stripe"),
            ("sumup", "SumUp"),
            ("tines", "Tines"),
            ("toast", "Toast"),
            ("tripadvisor", "Tripadvisor"),
            ("twilio", "Twilio"),
            ("udemy", "Udemy"),
            ("zoominfo", "ZoomInfo"),
        )
    ),
    *(
        Employer("ashby", board, name)
        for board, name in (
            ("notion", "Notion"),
            ("openai", "OpenAI"),
            ("vanta", "Vanta"),
            ("wayflyer", "Wayflyer"),
        )
    ),
)

_IRISH_PLACE = re.compile(r"\b(ireland|dublin|cork|galway|limerick|waterford|ie)\b", re.IGNORECASE)
#: Places that share a name with an Irish one. Belfast is in the UK, and there
#: is a Dublin in Ohio, California and Georgia, each with tech offices.
_NOT_IRISH = re.compile(
    r"northern\s+ireland|belfast|dublin,?\s*(?:oh|ohio|ca|california|ga|georgia|va|virginia)\b",
    re.IGNORECASE,
)


def is_irish_location(*locations: str | None) -> bool:
    """Does any of these location strings place the role in Ireland?

    Multi-site postings ("London; Dublin") count, since the role can be held
    from Ireland. Each site is judged on its own, so "Belfast; Dublin" is Irish
    and "Belfast" alone is not.
    """
    for location in locations:
        for site in re.split(r"[;|/]|\bor\b", location or ""):
            if _IRISH_PLACE.search(site) and not _NOT_IRISH.search(site):
                return True
    return False


class AtsScraper(BaseScraper):
    """Greenhouse and Ashby public job boards — Irish data roles only, no key."""

    source = JobSource.ATS
    default_country = "IE"
    GREENHOUSE_URL = "https://boards-api.greenhouse.io/v1/boards/{board}/jobs"
    ASHBY_URL = "https://api.ashbyhq.com/posting-api/job-board/{board}"

    def __init__(self, *args: Any, employers: tuple[Employer, ...] = EMPLOYERS, **kwargs: Any):
        super().__init__(*args, **kwargs)
        self.employers = employers

    def scrape(self, limit: int) -> Iterator[JobPosting]:
        count = failed = 0
        seen: set[tuple[str, str]] = set()
        for employer in self.employers:
            if count >= limit:
                break
            try:
                records = self._fetch(employer)
            except Exception as exc:  # one board gone must not cost the other 32
                failed += 1
                log.warning("ats.board.failed", board=employer.board, error=str(exc)[:200])
                continue
            for record in records:
                if count >= limit:
                    break
                posting = self._parse(employer, record)
                # A job open in "Ireland" and in "Cork; Dublin" is one job
                # posted twice, with text that differs by a line — so the
                # content hash keeps both. Greenhouse's internal_job_id is shared
                # by every copy; Ashby posts a job once, with secondaryLocations.
                job = str(record.get("internal_job_id") or record.get("id"))
                if posting is None or (employer.board, job) in seen:
                    continue
                seen.add((employer.board, job))
                count += 1
                yield posting
        log.info("ats.scrape.done", count=count, boards=len(self.employers), failed=failed)

    def _fetch(self, employer: Employer) -> list[dict[str, Any]]:
        if employer.ats == "greenhouse":
            url = self.GREENHOUSE_URL.format(board=employer.board)
            return self.http.get_json(url, params={"content": "true"}).get("jobs", [])
        url = self.ASHBY_URL.format(board=employer.board)
        return self.http.get_json(url, params={"includeCompensation": "true"}).get("jobs", [])

    def _parse(self, employer: Employer, record: dict[str, Any]) -> JobPosting | None:
        if employer.ats == "greenhouse":
            return self._parse_greenhouse(employer, record)
        return self._parse_ashby(employer, record)

    def _parse_greenhouse(self, employer: Employer, record: dict[str, Any]) -> JobPosting | None:
        job_id, title, url = record.get("id"), record.get("title"), record.get("absolute_url")
        # Greenhouse lists a multi-site job once per site. ``location`` is this
        # posting's own site; ``offices`` are every site of the job, so reading
        # them made the Lisbon copy of a Dublin job look Irish. They are only a
        # fallback for a posting with no location of its own.
        location = (record.get("location") or {}).get("name")
        sites = (
            [location]
            if location
            else [o.get("location") or o.get("name") for o in record.get("offices") or []]
        )
        if not job_id or not url or not is_target_role(title):
            return None
        if not is_irish_location(*sites):
            return None
        return self.build_posting(
            source_job_id=f"greenhouse:{employer.board}:{job_id}",
            source_url=url,
            title=str(title).strip(),
            company_name=record.get("company_name") or employer.name,
            # Greenhouse entity-escapes the HTML ("&lt;p&gt;"); unescape it so
            # the description is HTML like every other source's.
            description_raw=html.unescape(record.get("content") or "") or None,
            location_raw=location,
            posted_at=parse_iso_dt(record.get("first_published") or record.get("updated_at")),
            raw_payload={k: v for k, v in record.items() if k != "content"},
        )

    def _parse_ashby(self, employer: Employer, record: dict[str, Any]) -> JobPosting | None:
        job_id, title, url = record.get("id"), record.get("title"), record.get("jobUrl")
        if not job_id or not url or not is_target_role(title):
            return None
        address = ((record.get("address") or {}).get("postalAddress")) or {}
        sites = [record.get("location"), address.get("addressCountry")]
        sites += [s.get("location") for s in record.get("secondaryLocations") or []]
        if not is_irish_location(*sites):
            return None
        compensation = record.get("compensation") or {}
        return self.build_posting(
            source_job_id=f"ashby:{employer.board}:{job_id}",
            source_url=url,
            apply_url=record.get("applyUrl"),
            title=str(title).strip(),
            company_name=employer.name,
            description_raw=record.get("descriptionHtml") or record.get("descriptionPlain"),
            location_raw=record.get("location"),
            is_remote_raw=record.get("isRemote"),
            posted_at=parse_iso_dt(record.get("publishedAt")),
            salary_raw=compensation.get("compensationTierSummary"),
            employment_type_raw=record.get("employmentType"),
            raw_payload={
                k: v for k, v in record.items() if k not in ("descriptionHtml", "descriptionPlain")
            },
        )
