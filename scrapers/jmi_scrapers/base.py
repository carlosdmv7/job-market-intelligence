"""Base scraper abstraction + HTTP session wrappers.

The 0€ default uses :class:`HttpSession` (plain ``httpx``) against free, public,
no-key job APIs. :class:`ScrapflySession` stays available for the
improvement-section sources (LinkedIn/Indeed) but is imported lazily so neither
``httpx``-only scrapers nor the JSON-LD helpers require the Scrapfly SDK.

Concrete scrapers subclass :class:`BaseScraper`, declare their ``source``, and
yield canonical :class:`~jmi_core.schema.raw.JobPosting` records;
:meth:`build_posting` fills provenance + derived defaults.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, ClassVar

from jmi_core import SCHEMA_VERSION
from jmi_core.logging import get_logger
from jmi_core.schema import JobPosting, JobSource
from jmi_core.text import detect_language, strip_html

if TYPE_CHECKING:
    from collections.abc import Iterator

    from jmi_core.settings import Settings

log = get_logger(__name__)

_DEFAULT_UA = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0 Safari/537.36 JMI-Engine/0.2 (+https://github.com/REPLACE_ME)"
)


class HttpSession:
    """Tiny ``httpx`` wrapper: sane UA, timeouts, retries, JSON/text helpers."""

    def __init__(self, *, timeout: float = 30.0, headers: dict[str, str] | None = None) -> None:
        import httpx  # lazy

        self._client = httpx.Client(
            timeout=timeout,
            follow_redirects=True,
            headers={"User-Agent": _DEFAULT_UA, "Accept": "application/json", **(headers or {})},
            transport=httpx.HTTPTransport(retries=2),
        )

    def get_json(self, url: str, *, params: dict[str, Any] | None = None,
                 headers: dict[str, str] | None = None) -> Any:
        resp = self._client.get(url, params=params, headers=headers)
        resp.raise_for_status()
        return resp.json()

    def get_text(self, url: str, *, params: dict[str, Any] | None = None,
                 headers: dict[str, str] | None = None) -> str:
        resp = self._client.get(url, params=params, headers=headers)
        resp.raise_for_status()
        return resp.text

    def close(self) -> None:
        self._client.close()


class ScrapflySession:
    """Improvement-section wrapper over the Scrapfly SDK (asp/render_js)."""

    def __init__(self, api_key: str) -> None:
        from scrapfly import ScrapflyClient  # lazy

        self._client = ScrapflyClient(key=api_key)

    def fetch(self, url: str, *, asp: bool = True, render_js: bool = False,
              country: str | None = None) -> Any:
        from scrapfly import ScrapeConfig  # lazy

        return self._client.scrape(
            ScrapeConfig(url=url, asp=asp, render_js=render_js, country=country)
        )


class BaseScraper(ABC):
    """Abstract scraper. Subclasses set ``source`` and implement :meth:`scrape`."""

    source: ClassVar[JobSource]
    #: ISO 3166-1 alpha-2 default when the source is single-country.
    default_country: ClassVar[str | None] = None

    def __init__(
        self,
        settings: Settings,
        *,
        run_id: str | None = None,
        http: HttpSession | None = None,
    ) -> None:
        self.settings = settings
        self.run_id = run_id
        self._http = http
        self._scrapfly: ScrapflySession | None = None

    @property
    def http(self) -> HttpSession:
        if self._http is None:
            self._http = HttpSession()
        return self._http

    @property
    def scrapfly(self) -> ScrapflySession:
        if self._scrapfly is None:
            if not self.settings.scrapfly_key:
                raise RuntimeError("SCRAPFLY_KEY is not configured")
            self._scrapfly = ScrapflySession(self.settings.scrapfly_key)
        return self._scrapfly

    @abstractmethod
    def scrape(self, limit: int) -> Iterator[JobPosting]:
        """Yield up to ``limit`` postings for this source."""
        raise NotImplementedError

    # -- helper for subclasses -------------------------------------------
    def build_posting(
        self,
        *,
        source_job_id: str,
        source_url: str,
        title: str,
        company_name: str | None = None,
        company_url: str | None = None,
        description_raw: str | None = None,
        location_raw: str | None = None,
        country_code: str | None = None,
        is_remote_raw: bool | None = None,
        posted_at: datetime | None = None,
        valid_through: datetime | None = None,
        salary_raw: str | None = None,
        employment_type_raw: str | None = None,
        seniority_raw: str | None = None,
        apply_url: str | None = None,
        detected_language: str | None = None,
        raw_payload: dict[str, Any] | None = None,
    ) -> JobPosting:
        clean_desc = strip_html(description_raw)
        return JobPosting(
            source=self.source,
            source_job_id=source_job_id,
            source_url=source_url,
            apply_url=apply_url,
            ingestion_run_id=self.run_id,
            scraped_at=datetime.now(timezone.utc),
            title=title,
            company_name=company_name,
            company_url=company_url,
            description_raw=description_raw,
            detected_language=detected_language or detect_language(clean_desc),
            location_raw=location_raw,
            country_code=country_code or self.default_country,
            is_remote_raw=is_remote_raw,
            posted_at=posted_at,
            valid_through=valid_through,
            salary_raw=salary_raw,
            employment_type_raw=employment_type_raw,
            seniority_raw=seniority_raw,
            raw_payload=raw_payload,
            schema_version=SCHEMA_VERSION,
        )


def parse_iso_dt(value: Any) -> datetime | None:
    """Parse an ISO-ish timestamp to UTC tz-aware; tolerant of None/garbage."""
    if not value or not isinstance(value, str):
        return None
    text = value.strip().replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        try:
            dt = datetime.strptime(text[:10], "%Y-%m-%d")
        except ValueError:
            return None
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt.astimezone(timezone.utc)
