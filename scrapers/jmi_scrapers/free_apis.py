"""Free, public job-board API scrapers — the 0€ default source set.

All use :class:`HttpSession` (plain httpx). Remotive, Arbeitnow, and RemoteOK
need no key or registration. Adzuna needs a free key (improvement hook) but
covers per-country search (NL/ES/DE/FR/IT/... — note: Adzuna has no IE or PT).

Each ``_parse`` is pure and unit-tested; ``scrape`` handles paging.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from jmi_core.logging import get_logger
from jmi_core.schema import JobSource

from jmi_scrapers.base import BaseScraper, parse_iso_dt

if TYPE_CHECKING:
    from collections.abc import Iterator

    from jmi_core.schema import JobPosting
    from jmi_core.settings import Settings

log = get_logger(__name__)


def _unix_to_dt(value: Any) -> datetime | None:
    try:
        return datetime.fromtimestamp(int(value), tz=timezone.utc)
    except (TypeError, ValueError, OSError):
        return None


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


class AdzunaScraper(BaseScraper):
    """https://api.adzuna.com — per-country search (free key). Improvement hook.

    Supported countries include nl, es, de, fr, it, gb, at, be, pl, ch (NOT ie/pt).
    """

    source = JobSource.ADZUNA
    BASE_URL = "https://api.adzuna.com/v1/api/jobs"
    PER_PAGE = 50

    def __init__(self, settings: Settings, *, country: str = "nl", what: str | None = None,
                 **kwargs: Any) -> None:
        super().__init__(settings, **kwargs)
        self.country = country.lower()
        self.what = what

    def scrape(self, limit: int) -> Iterator[JobPosting]:
        if not (self.settings.adzuna_app_id and self.settings.adzuna_app_key):
            raise RuntimeError("Adzuna requires ADZUNA_APP_ID and ADZUNA_APP_KEY")
        page, count = 1, 0
        while count < limit:
            data = self.http.get_json(
                f"{self.BASE_URL}/{self.country}/search/{page}",
                params={
                    "app_id": self.settings.adzuna_app_id,
                    "app_key": self.settings.adzuna_app_key,
                    "results_per_page": min(self.PER_PAGE, limit),
                    "what": self.what or "data engineer",
                    "content-type": "application/json",
                },
            )
            results = data.get("results", [])
            if not results:
                break
            for record in results:
                if count >= limit:
                    return
                posting = self._parse(record)
                if posting is not None:
                    count += 1
                    yield posting
            page += 1
        log.info("adzuna.scrape.done", country=self.country, count=count)

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
