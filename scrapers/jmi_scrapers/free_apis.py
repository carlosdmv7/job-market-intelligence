"""Free, public job-board API scrapers — the 0€ default source set.

All use :class:`HttpSession` (plain httpx). Remotive, Arbeitnow, and RemoteOK
need no key or registration. Adzuna needs a free key (improvement hook) but
covers per-country search (NL/ES/DE/FR/IT/... — note: Adzuna has no IE or PT).

Each ``_parse`` is pure and unit-tested; ``scrape`` handles paging.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, ClassVar

from jmi_core.logging import get_logger
from jmi_core.schema import JobSource
from jmi_scrapers.base import BaseScraper, parse_iso_dt

if TYPE_CHECKING:
    from collections.abc import Iterator, Sequence

    from jmi_core.schema import JobPosting
    from jmi_core.settings import Settings

log = get_logger(__name__)


def _unix_to_dt(value: Any) -> datetime | None:
    try:
        return datetime.fromtimestamp(int(value), tz=UTC)
    except (TypeError, ValueError, OSError):
        return None


#: Data-role queries swept by the per-country scrapers (one search per term),
#: so a single ingest yields a broad, comparable local corpus per market.
DATA_ROLE_QUERIES: tuple[str, ...] = (
    "data engineer",
    "analytics engineer",
    "data analyst",
    "data scientist",
    "machine learning engineer",
    "data platform",
)


class RemotiveScraper(BaseScraper):
    """https://remotive.com/api/remote-jobs — remote tech jobs, no key."""

    source = JobSource.REMOTIVE
    API_URL = "https://remotive.com/api/remote-jobs"

    def scrape(self, limit: int) -> Iterator[JobPosting]:
        data = self.http.get_json(self.API_URL, params={"limit": limit})
        count = 0
        for record in data.get("jobs", []):
            if count >= limit:
                break
            posting = self._parse(record)
            if posting is not None:
                count += 1
                yield posting
        log.info("remotive.scrape.done", count=count)

    def _parse(self, record: dict[str, Any]) -> JobPosting | None:
        job_id, title, url = record.get("id"), record.get("title"), record.get("url")
        if not job_id or not title or not url:
            return None
        return self.build_posting(
            source_job_id=str(job_id),
            source_url=url,
            title=title,
            company_name=record.get("company_name"),
            description_raw=record.get("description"),
            location_raw=record.get("candidate_required_location"),
            is_remote_raw=True,
            posted_at=parse_iso_dt(record.get("publication_date")),
            salary_raw=record.get("salary") or None,
            employment_type_raw=record.get("job_type"),
            raw_payload=record,
        )


class ArbeitnowScraper(BaseScraper):
    """https://www.arbeitnow.com/api/job-board-api — EU (DE-heavy) jobs, no key."""

    source = JobSource.ARBEITNOW
    API_URL = "https://www.arbeitnow.com/api/job-board-api"

    def scrape(self, limit: int) -> Iterator[JobPosting]:
        url: str | None = self.API_URL
        count = 0
        while url and count < limit:
            data = self.http.get_json(url)
            for record in data.get("data", []):
                if count >= limit:
                    return
                posting = self._parse(record)
                if posting is not None:
                    count += 1
                    yield posting
            url = (data.get("links") or {}).get("next")
        log.info("arbeitnow.scrape.done", count=count)

    def _parse(self, record: dict[str, Any]) -> JobPosting | None:
        slug, title, url = record.get("slug"), record.get("title"), record.get("url")
        if not slug or not title or not url:
            return None
        job_types = record.get("job_types") or []
        return self.build_posting(
            source_job_id=str(slug),
            source_url=url,
            title=title,
            company_name=record.get("company_name"),
            description_raw=record.get("description"),
            location_raw=record.get("location"),
            is_remote_raw=bool(record.get("remote")) if "remote" in record else None,
            posted_at=_unix_to_dt(record.get("created_at")),
            employment_type_raw=", ".join(job_types) if job_types else None,
            raw_payload=record,
        )


class RemoteOkScraper(BaseScraper):
    """https://remoteok.com/api — remote jobs, no key (needs a real UA header)."""

    source = JobSource.REMOTEOK
    API_URL = "https://remoteok.com/api"

    def scrape(self, limit: int) -> Iterator[JobPosting]:
        data = self.http.get_json(self.API_URL)
        # Element 0 is a legal/disclaimer object; real jobs have an "id".
        records = [r for r in data if isinstance(r, dict) and r.get("id")]
        count = 0
        for record in records:
            if count >= limit:
                break
            posting = self._parse(record)
            if posting is not None:
                count += 1
                yield posting
        log.info("remoteok.scrape.done", count=count)

    def _parse(self, record: dict[str, Any]) -> JobPosting | None:
        job_id = record.get("id")
        title = record.get("position") or record.get("title")
        url = record.get("url")
        if not job_id or not title or not url:
            return None
        return self.build_posting(
            source_job_id=str(job_id),
            source_url=url,
            title=title,
            company_name=record.get("company"),
            description_raw=record.get("description"),
            location_raw=record.get("location") or None,
            is_remote_raw=True,
            posted_at=parse_iso_dt(record.get("date")),
            salary_raw=self._salary(record),
            employment_type_raw=", ".join(record.get("tags", [])[:3]) or None,
            raw_payload=record,
        )

    @staticmethod
    def _salary(record: dict[str, Any]) -> str | None:
        lo, hi = record.get("salary_min"), record.get("salary_max")
        if lo and hi:
            return f"USD {lo}-{hi}"
        return f"USD {lo or hi}" if (lo or hi) else None


class JobTechScraper(BaseScraper):
    """https://jobsearch.api.jobtechdev.se — Sweden's public employment service.

    Free, no key, no registration (Arbetsförmedlingen / Platsbanken open API).
    Country is always SE. Postings carry the employer's organisationsnummer,
    which is publicly verifiable at Bolagsverket — the Swedish analogue of the
    KvK audit trail on the IND cross-reference.
    """

    source = JobSource.JOBTECH
    API_URL = "https://jobsearch.api.jobtechdev.se/search"
    PER_PAGE = 100  # the API's maximum
    DEFAULT_WHATS: ClassVar[tuple[str, ...]] = DATA_ROLE_QUERIES

    def __init__(self, settings: Settings, *, whats: Sequence[str] | None = None, **kwargs: Any):
        super().__init__(settings, **kwargs)
        self.whats = list(whats) if whats else list(self.DEFAULT_WHATS)

    def scrape(self, limit: int) -> Iterator[JobPosting]:
        per_query = max(1, -(-limit // len(self.whats)))  # ceil, spread across roles
        seen: set[str] = set()
        total = 0
        for what in self.whats:
            if total >= limit:
                break
            data = self.http.get_json(
                self.API_URL,
                params={"q": what, "limit": min(per_query, self.PER_PAGE)},
            )
            for record in data.get("hits", []):
                if total >= limit:
                    break
                posting = self._parse(record)
                if posting is None or posting.source_job_id in seen:
                    continue
                seen.add(posting.source_job_id)
                total += 1
                yield posting
        log.info("jobtech.scrape.done", queries=len(self.whats), count=total)

    def _parse(self, record: dict[str, Any]) -> JobPosting | None:
        job_id = record.get("id")
        title = record.get("headline")
        url = record.get("webpage_url")
        if not job_id or not title or not url:
            return None
        employer = record.get("employer") or {}
        workplace = record.get("workplace_address") or {}
        description = record.get("description") or {}
        application = record.get("application_details") or {}
        employment_type = record.get("employment_type") or {}
        location = ", ".join(
            part for part in (workplace.get("municipality"), workplace.get("region")) if part
        )
        return self.build_posting(
            source_job_id=str(job_id),
            source_url=url,
            apply_url=application.get("url"),
            title=title,
            company_name=employer.get("name"),
            company_url=employer.get("url"),
            description_raw=description.get("text"),
            location_raw=location or None,
            country_code="SE",
            posted_at=parse_iso_dt(record.get("publication_date")),
            valid_through=parse_iso_dt(record.get("application_deadline")),
            salary_raw=record.get("salary_description"),
            employment_type_raw=employment_type.get("label"),
            raw_payload=record,
        )


class AdzunaScraper(BaseScraper):
    """https://api.adzuna.com — per-country search (free key). Improvement hook.

    Supported countries include nl, es, de, fr, it, gb, at, be, pl, ch (NOT ie/pt).
    """

    source = JobSource.ADZUNA
    BASE_URL = "https://api.adzuna.com/v1/api/jobs"
    PER_PAGE = 50
    DEFAULT_WHATS: ClassVar[tuple[str, ...]] = DATA_ROLE_QUERIES

    def __init__(
        self,
        settings: Settings,
        *,
        country: str = "nl",
        what: str | None = None,
        whats: Sequence[str] | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(settings, **kwargs)
        self.country = country.lower()
        # Priority: explicit list > single term > the default sweep.
        self.whats = list(whats) if whats else ([what] if what else list(self.DEFAULT_WHATS))

    def scrape(self, limit: int) -> Iterator[JobPosting]:
        if not (self.settings.adzuna_app_id and self.settings.adzuna_app_key):
            raise RuntimeError("Adzuna requires ADZUNA_APP_ID and ADZUNA_APP_KEY")
        per_query = max(1, -(-limit // len(self.whats)))  # ceil, spread across roles
        seen: set[str] = set()
        total = 0
        for what in self.whats:
            if total >= limit:
                break
            q_count, page = 0, 1
            while q_count < per_query and total < limit:
                data = self.http.get_json(
                    f"{self.BASE_URL}/{self.country}/search/{page}",
                    params={
                        "app_id": self.settings.adzuna_app_id,
                        "app_key": self.settings.adzuna_app_key,
                        "results_per_page": self.PER_PAGE,
                        "what": what,
                        "content-type": "application/json",
                    },
                )
                results = data.get("results", [])
                if not results:
                    break
                for record in results:
                    if q_count >= per_query or total >= limit:
                        break
                    posting = self._parse(record)
                    if posting is None or posting.source_job_id in seen:
                        continue
                    seen.add(posting.source_job_id)
                    q_count += 1
                    total += 1
                    yield posting
                page += 1
        log.info("adzuna.scrape.done", country=self.country, queries=len(self.whats), count=total)

    def _parse(self, record: dict[str, Any]) -> JobPosting | None:
        job_id = record.get("id")
        title = record.get("title")
        url = record.get("redirect_url")
        if not job_id or not title or not url:
            return None
        company = record.get("company") or {}
        location = record.get("location") or {}
        return self.build_posting(
            source_job_id=str(job_id),
            source_url=url,
            title=title,
            company_name=company.get("display_name") if isinstance(company, dict) else None,
            description_raw=record.get("description"),
            location_raw=location.get("display_name") if isinstance(location, dict) else None,
            country_code=self.country.upper(),
            posted_at=parse_iso_dt(record.get("created")),
            salary_raw=self._salary(record),
            employment_type_raw=record.get("contract_time"),
            raw_payload=record,
        )

    @staticmethod
    def _salary(record: dict[str, Any]) -> str | None:
        lo, hi = record.get("salary_min"), record.get("salary_max")
        if lo and hi:
            return f"{lo:.0f}-{hi:.0f}"
        return f"{(lo or hi):.0f}" if (lo or hi) else None
