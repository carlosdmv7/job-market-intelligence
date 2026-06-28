"""LLM enrichment contract (Claude Haiku output).

One instance == one enrichment of one *content version* of a posting. Keyed by
``content_hash`` so each distinct content is enriched exactly once, no matter
how many daily snapshots observe it. Re-enrich only when content_hash changes
or ``prompt_version`` / ``model`` is bumped.

Lands in `raw.raw_job_enrichment`; joined to `raw.raw_job_postings` on
content_hash downstream.
"""

from __future__ import annotations

from datetime import datetime, timezone

from pydantic import BaseModel, ConfigDict, Field, field_validator

from jmi_core.schema.enums import (
    EmploymentType,
    JobSource,
    RemotePolicy,
    Seniority,
)
from jmi_core.schema.values import VisaSponsorship


class JobEnrichment(BaseModel):
    """Normalized, model-derived attributes for a posting content version."""

    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    # --- keys & lineage --------------------------------------------------
    content_hash: str = Field(..., description="FK to raw_job_postings.content_hash")
    source: JobSource
    source_job_id: str = Field(..., min_length=1)

    enriched_at: datetime = Field(..., description="UTC, tz-aware")
    model: str = Field(..., description="Model id, e.g. claude-haiku-4-5-20251001")
    prompt_version: str = Field(..., description="Enrichment prompt version; bump => re-enrich")
    schema_version: str = Field(..., description="jmi_core.SCHEMA_VERSION at enrichment time")

    # --- cost / observability (Haiku is cheap, but we still track) -------
    input_tokens: int | None = Field(None, ge=0)
    output_tokens: int | None = Field(None, ge=0)
    cost_usd: float | None = Field(None, ge=0)

    # --- normalized classifications --------------------------------------
    normalized_role: str | None = Field(None, description="Canonical title, e.g. 'Analytics Engineer'")
    role_family: str | None = Field(None, description="e.g. 'Data Engineering', 'Data Science'")
    seniority: Seniority = Seniority.UNKNOWN
    employment_type: EmploymentType = EmploymentType.UNKNOWN
    remote_policy: RemotePolicy = RemotePolicy.UNKNOWN
    technologies: list[str] = Field(default_factory=list, description="Normalized tech/skill tokens")

    # --- killer feature: visa + relocation fit ---------------------------
    visa: VisaSponsorship
    requires_local_language: bool | None = Field(
        None, description="True if a non-English local language (NL/DE/PT...) is required"
    )
    working_languages: list[str] | None = Field(
        None, description="ISO 639-1 codes the role requires/uses"
    )
    english_sufficient: bool | None = Field(
        None, description="True if English alone is enough to do the job"
    )
    relocation_support: bool | None = Field(
        None, description="True if relocation assistance is mentioned (distinct from visa)"
    )

    # --- quality ---------------------------------------------------------
    enrichment_confidence: float | None = Field(
        None, ge=0.0, le=1.0, description="Model's overall confidence in this enrichment"
    )
    raw_response: dict | None = Field(
        None, description="Full model JSON response, retained for audit/debug"
    )

    @field_validator("enriched_at")
    @classmethod
    def _ensure_utc(cls, v: datetime) -> datetime:
        if v.tzinfo is None:
            raise ValueError("enriched_at must be timezone-aware (UTC)")
        return v.astimezone(timezone.utc)
