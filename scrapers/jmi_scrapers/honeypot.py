"""Honeypot.io scraper (Phase 0 — the first working source).

Honeypot is a Netherlands-focused developer job board with a JSON API, which
makes it the cleanest first source: structured fields, no JS rendering, low
anti-bot friction. We still route through Scrapfly for consistent egress and
retries.

⚠️ The API base URL and record field names below are *best-effort* and must be
confirmed against Honeypot's live API (Carlos owns that knowledge). They are
isolated in :attr:`HoneypotScraper.API_URL` and :meth:`_parse_record` so
adjusting them is a one-spot change. The mapping logic itself is unit-tested.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from jmi_core.logging import get_logger
from jmi_core.schema import JobSource

from jmi_scrapers.base import BaseScraper

if TYPE_CHECKING:
    from collections.abc import Iterator

    from jmi_core.schema import JobPosting

log = get_logger(__name__)


class HoneypotScraper(BaseScraper):
    source = JobSource.HONEYPOT
    default_country = "NL"

    #: Confirm against Honeypot's real API. Overridable for tests / changes.
    API_URL = "https://www.honeypot.io/api/v1/jobs"
    PAGE_SIZE = 50

    def scrape(self, limit: int) -> Iterator[JobPosting]:
        seen = 0
        page = 1
        while seen < limit:
            payload = self.http.get_json(
                self.API_URL, params={"page": page, "per_page": self.PAGE_SIZE}
            )
            records = self._records(payload)
            if not records:
                break
            for record in records:
                if seen >= limit:
                    return
                posting = self._parse_record(record)
                if posting is not None:
                    seen += 1
                    yield posting
            page += 1
        log.info("honeypot.scrape.done", count=seen)

    @staticmethod
    def _records(payload: Any) -> list[dict[str, Any]]:
        """Tolerate both a bare list and an envelope like {"jobs": [...]}."""
        if isinstance(payload, list):
            return payload
        if isinstance(payload, dict):
            for key in ("jobs", "data", "results", "items"):
                if isinstance(payload.get(key), list):
                    return payload[key]
        return []

    def _parse_record(self, record: dict[str, Any]) -> JobPosting | None:
        """Map one Honeypot job record → JobPosting. Pure / unit-tested."""
        job_id = record.get("id") or record.get("slug") or record.get("uuid")
        title = record.get("title") or record.get("position") or record.get("role")
        if job_id is None or not title:
            log.warning("honeypot.parse.skip", reason="missing id/title", record_keys=list(record))
            return None

        company = record.get("company") or {}
        company_name = (
            company.get("name") if isinstance(company, dict) else company
        ) or record.get("company_name")

        url = record.get("url") or record.get("public_url") or f"{self.API_URL}/{job_id}"
        salary = record.get("salary") or self._salary_range(record)
        remote = record.get("remote")

        return self.build_posting(
            source_job_id=str(job_id),
            source_url=str(url),
            apply_url=record.get("apply_url"),
            title=str(title),
            company_name=str(company_name) if company_name else None,
            description_raw=record.get("description") or record.get("body"),
            location_raw=record.get("location") or record.get("city"),
            country_code="NL",
            is_remote_raw=bool(remote) if remote is not None else None,
            salary_raw=str(salary) if salary else None,
            employment_type_raw=record.get("employment_type") or record.get("contract_type"),
            seniority_raw=record.get("seniority") or record.get("experience_level"),
            raw_payload=record,
        )

    @staticmethod
    def _salary_range(record: dict[str, Any]) -> str | None:
        lo, hi = record.get("salary_min"), record.get("salary_max")
        currency = record.get("salary_currency") or "EUR"
        if lo and hi:
            return f"{currency} {lo}-{hi}"
        if lo or hi:
            return f"{currency} {lo or hi}"
        return None
