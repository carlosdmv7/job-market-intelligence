"""Scraper registry: name → scraper class.

Default 0€ set: remotive, arbeitnow, remoteok (free, no key). ``jobtech`` is
also keyless (Sweden's public employment service). ``adzuna`` needs a free key;
``honeypot`` is kept as a hook (confirm its API). Scrapfly-based sources
(LinkedIn/Indeed) are an improvement-section addition.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from jmi_scrapers.base import BaseScraper
from jmi_scrapers.free_apis import (
    AdzunaScraper,
    ArbeitnowScraper,
    JobTechScraper,
    RemoteOkScraper,
    RemotiveScraper,
)
from jmi_scrapers.honeypot import HoneypotScraper

if TYPE_CHECKING:
    from jmi_core.settings import Settings

#: Free, no-registration sources run by default.
DEFAULT_SOURCES: tuple[str, ...] = ("remotive", "arbeitnow", "remoteok")

SCRAPERS: dict[str, type[BaseScraper]] = {
    "remotive": RemotiveScraper,
    "arbeitnow": ArbeitnowScraper,
    "remoteok": RemoteOkScraper,
    "adzuna": AdzunaScraper,  # needs ADZUNA_APP_ID / ADZUNA_APP_KEY
    "jobtech": JobTechScraper,  # Sweden (Platsbanken) — free, no key
    "honeypot": HoneypotScraper,  # confirm API before relying on it
}


def available() -> list[str]:
    return sorted(SCRAPERS)


def get_scraper(name: str, settings: Settings, **kwargs: object) -> BaseScraper:
    try:
        cls = SCRAPERS[name]
    except KeyError:
        raise KeyError(f"Unknown scraper '{name}'. Available: {', '.join(available())}") from None
    return cls(settings, **kwargs)  # type: ignore[arg-type]
