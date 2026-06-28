"""Canonical raw JobPosting contract.

One instance == one *observation* of a posting from one source at one scrape
time. The raw layer is an append-only event log: the same logical posting
produces one row per daily scrape, which is what makes
``FT_JOB_SNAPSHOT_DAILY`` and time-series trends possible downstream.

Identity:
  * logical key per source  -> (source, source_job_id)
  * content version / change -> content_hash (computed)
  * cross-source canonical id -> NOT here. Resolved in dbt `int_` via
    deterministic hash + embedding edge cases (see ADR on dedup).

These fields are strictly *as-scraped*. Normalized enums, parsed salary, and
LLM judgements live in their own models, never here.
"""

from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, computed_field, field_validator

from jmi_core.schema.enums import JobSource

_WS = re.compile(r"\s+")
_HASH_SEP = "\x1f"  # unit separator, will not appear in scraped text


def _norm(value: str | None) -> str:
    """Lowercase, collapse whitespace, strip — for stable hashing only."""
    if not value:
        return ""
    return _WS.sub(" ", value).strip().lower()


def compute_content_hash(
    *,
    source: JobSource | str,
    source_job_id: str,
    title: str | None,
    company_name: str | None,
    location_raw: str | None,
    salary_raw: str | None,
    description_raw: str | None,
) -> str:
    """Deterministic content version hash for a single source's posting.

    Stable across processes and languages (the dbt side recomputes this with
    the identical recipe). Changing the recipe is a schema-version bump.
    The hash is intentionally scoped to one source (includes source +
    source_job_id); cross-source clustering is a separate concern in dbt.
    """
    source_value = source.value if isinstance(source, JobSource) else str(source)
    parts = [
        source_value,
        _norm(source_job_id),
        _norm(title),
        _norm(company_name),
        _norm(location_raw),
        _norm(salary_raw),
        _norm(description_raw),
    ]
    digest = hashlib.sha256(_HASH_SEP.join(parts).encode("utf-8"))
    return digest.hexdigest()


class JobPosting(BaseModel):
    """Raw, as-scraped posting. The write contract for the `raw` schema."""

    model_config = ConfigDict(
        extra="forbid",            # surface scraper field drift loudly
        str_strip_whitespace=True,
        validate_assignment=True,
    )

    # --- identity & provenance -------------------------------------------
    source: JobSource
    source_job_id: str = Field(..., min_length=1, description="The platform's own posting id")
    source_url: str
    apply_url: str | None = Field(None, description="External apply link when it differs from source_url")
    ingestion_run_id: str | None = Field(None, description="Prefect flow run id that produced this row")
    scraped_at: datetime = Field(..., description="UTC, tz-aware; the observation timestamp")

    # --- core content (as posted) ----------------------------------------
    title: str = Field(..., min_length=1)
    company_name: str | None = Field(None, description="None for confidential/blind postings")
    company_url: str | None = None
    description_raw: str | None = Field(None, description="Full description text or HTML, original language")
    detected_language: str | None = Field(
        None, description="ISO 639-1, cheap detection at ingestion; enrichment may override", max_length=2
    )

    # --- location --------------------------------------------------------
    location_raw: str | None = Field(None, description="As posted, e.g. 'Amsterdam, North Holland, NL'")
    country_code: str | None = Field(
        None, description="ISO 3166-1 alpha-2 when derivable at scrape time (e.g. Honeypot=NL)", max_length=2
    )
    is_remote_raw: bool | None = Field(None, description="Source's own remote flag, if exposed")

    # --- dates -----------------------------------------------------------
    posted_at: datetime | None = Field(None, description="When the source says it was posted")
    valid_through: datetime | None = Field(None, description="Expiry, when provided (e.g. JSON-LD)")

    # --- as-posted descriptors (normalized versions live in enrichment) --
    salary_raw: str | None = Field(None, description="Compensation text exactly as posted")
    employment_type_raw: str | None = None
    seniority_raw: str | None = None

    # --- full source payload for replayability ---------------------------
    raw_payload: dict[str, Any] | None = Field(
        None, description="Complete source JSON/parsed blob; lets us re-parse without re-scraping"
    )

    # --- meta ------------------------------------------------------------
    schema_version: str = Field(..., description="jmi_core.SCHEMA_VERSION at write time")

    @field_validator("scraped_at", "posted_at", "valid_through")
    @classmethod
    def _ensure_utc(cls, v: datetime | None) -> datetime | None:
        """Reject naive datetimes; coerce everything to UTC."""
        if v is None:
            return v
        if v.tzinfo is None:
            raise ValueError("datetime must be timezone-aware (UTC)")
        return v.astimezone(timezone.utc)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def content_hash(self) -> str:
        """Content version of this source's posting; enrichment join key."""
        return compute_content_hash(
            source=self.source,
            source_job_id=self.source_job_id,
            title=self.title,
            company_name=self.company_name,
            location_raw=self.location_raw,
            salary_raw=self.salary_raw,
            description_raw=self.description_raw,
        )
