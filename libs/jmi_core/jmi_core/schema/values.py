"""Reusable value objects shared across raw / derived / enriched models."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from jmi_core.schema.enums import SalaryPeriod, VisaSponsorshipStatus


class Salary(BaseModel):
    """Parsed compensation.

    This is *deterministically derived* from ``JobPosting.salary_raw`` by the
    salary parser (Phase 2), not scraped and not LLM output. It is defined here
    as a shared contract; the parser's output materializes in the dbt staging
    layer (`stg_*`), keyed by ``content_hash``. Kept out of both ``raw`` (it is
    not as-scraped) and ``JobEnrichment`` (it is not an LLM judgement).
    """

    model_config = ConfigDict(extra="forbid")

    min_amount: float | None = Field(None, ge=0)
    max_amount: float | None = Field(None, ge=0)
    currency: str | None = Field(None, description="ISO 4217, e.g. EUR, GBP, USD", max_length=3)
    period: SalaryPeriod | None = None
    is_gross: bool | None = Field(None, description="True=gross, False=net, None=unknown")
    is_estimated: bool | None = Field(
        None, description="True when the source shows a market estimate, not an advertised figure"
    )


class VisaSponsorship(BaseModel):
    """LLM judgement on visa sponsorship — the killer feature.

    Carries a confidence and the literal evidence span so every flag is
    auditable in the Streamlit UI and rankable by certainty.
    """

    model_config = ConfigDict(extra="forbid")

    status: VisaSponsorshipStatus
    confidence: float = Field(..., ge=0.0, le=1.0)
    evidence: str | None = Field(
        None, description="Verbatim snippet from the posting that justifies the status", max_length=1000
    )
    reasoning: str | None = Field(
        None, description="One-sentence rationale from the model", max_length=500
    )
