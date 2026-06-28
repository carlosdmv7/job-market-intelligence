"""Canonical Job Market Intelligence schema contracts."""

from __future__ import annotations

from jmi_core.schema.enrichment import JobEnrichment
from jmi_core.schema.enums import (
    EmploymentType,
    JobSource,
    RemotePolicy,
    SalaryPeriod,
    Seniority,
    VisaSponsorshipStatus,
)
from jmi_core.schema.raw import JobPosting, compute_content_hash
from jmi_core.schema.values import Salary, VisaSponsorship

__all__ = [
    # raw
    "JobPosting",
    "compute_content_hash",
    # enrichment
    "JobEnrichment",
    # value objects
    "Salary",
    "VisaSponsorship",
    # enums
    "JobSource",
    "Seniority",
    "RemotePolicy",
    "EmploymentType",
    "SalaryPeriod",
    "VisaSponsorshipStatus",
]
