"""Controlled vocabularies for the canonical JobPosting contract.

All enums are :class:`enum.StrEnum` so they serialize cleanly to JSON / DuckDB
VARCHAR and remain dbt-friendly (you can `where seniority = 'senior'` without
casts). Validation lives in Pydantic; the warehouse stores the raw string values.
"""

from __future__ import annotations

from enum import StrEnum


class JobSource(StrEnum):
    """Where a posting was scraped from. One member per configured scraper."""

    # Free, no-registration public JSON APIs (the 0€ default set).
    REMOTIVE = "remotive"
    ARBEITNOW = "arbeitnow"
    REMOTEOK = "remoteok"

    # Free with a key (improvement hook — covers NL/ES/DE/IE/PT).
    ADZUNA = "adzuna"

    # Scrapfly-era / API sources (improvement hooks, not in the default path).
    LINKEDIN = "linkedin"
    INDEED = "indeed"
    HONEYPOT = "honeypot"
    TECHMEABROAD = "techmeabroad"
    INFOJOBS = "infojobs"
    STEPSTONE = "stepstone"
    IRISHJOBS = "irishjobs"
    ITJOBS = "itjobs"


# ---------------------------------------------------------------------------
# Enrichment vocabularies (LLM output). Keep these tight and stable: the
# enrichment prompt enumerates exactly these values, and changing a member is a
# schema-version bump because it invalidates historical comparisons.
# ---------------------------------------------------------------------------


class VisaSponsorshipStatus(StrEnum):
    """Visa sponsorship signal — the project's killer feature.

    ``explicit_no`` is deliberately distinct from ``unclear``: a posting that
    states "no sponsorship / must have EU work authorization" is a strong
    *negative* filter, not merely an absence of signal.
    """

    EXPLICIT_YES = "explicit_yes"  # posting explicitly offers sponsorship/relocation
    LIKELY_YES = "likely_yes"  # strong implicit signals (intl team, "open to relocation")
    UNCLEAR = "unclear"  # no signal either way
    LIKELY_NO = "likely_no"  # implicit signals against (local-only language, gov contract)
    EXPLICIT_NO = "explicit_no"  # posting explicitly rules out sponsorship


class Seniority(StrEnum):
    INTERN = "intern"
    JUNIOR = "junior"
    MID = "mid"
    SENIOR = "senior"
    LEAD = "lead"
    PRINCIPAL = "principal"
    MANAGER = "manager"
    UNKNOWN = "unknown"


class RemotePolicy(StrEnum):
    ONSITE = "onsite"
    HYBRID = "hybrid"
    REMOTE = "remote"
    REMOTE_COUNTRY_RESTRICTED = (
        "remote_country_restricted"  # remote but only from specific countries
    )
    UNKNOWN = "unknown"


class EmploymentType(StrEnum):
    FULL_TIME = "full_time"
    PART_TIME = "part_time"
    CONTRACT = "contract"
    FREELANCE = "freelance"
    INTERNSHIP = "internship"
    TEMPORARY = "temporary"
    UNKNOWN = "unknown"


class SalaryPeriod(StrEnum):
    YEAR = "year"
    MONTH = "month"
    DAY = "day"
    HOUR = "hour"
