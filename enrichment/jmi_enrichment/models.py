"""The LLM's structured-output contract.

This is *only* the classification fields Claude produces — deliberately
separate from :class:`~jmi_core.schema.enrichment.JobEnrichment`, which adds
lineage/cost metadata the model must not invent. The classifier wraps an
``LLMJobClassification`` into a full ``JobEnrichment`` after the call.

Enums and the visa value object are reused from ``jmi_core`` so the prompt, the
warehouse, and the marts all speak the same vocabulary.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from jmi_core.schema import (
    EmploymentType,
    RemotePolicy,
    Seniority,
    VisaSponsorship,
)


class LLMJobClassification(BaseModel):
    """What Claude returns for one job posting (validated via structured output)."""

    model_config = ConfigDict(extra="forbid")

    normalized_role: str | None = Field(
        None, description="Canonical role title, e.g. 'Analytics Engineer'"
    )
    role_family: str | None = Field(
        None, description="Broad family, e.g. 'Data Engineering' / 'Data Science'"
    )
    seniority: Seniority = Seniority.UNKNOWN
    employment_type: EmploymentType = EmploymentType.UNKNOWN
    remote_policy: RemotePolicy = RemotePolicy.UNKNOWN
    technologies: list[str] = Field(
        default_factory=list, description="Normalized tech/skill tokens, deduped, lowercased"
    )

    visa: VisaSponsorship

    requires_local_language: bool | None = Field(
        None, description="True if a non-English local language is required to do the job"
    )
    working_languages: list[str] | None = Field(
        None, description="ISO 639-1 codes the role requires/uses"
    )
    english_sufficient: bool | None = Field(None, description="True if English alone is enough")
    relocation_support: bool | None = Field(
        None, description="True if relocation assistance is mentioned (distinct from visa)"
    )
    enrichment_confidence: float | None = Field(
        None, ge=0.0, le=1.0, description="Overall confidence in this classification"
    )
