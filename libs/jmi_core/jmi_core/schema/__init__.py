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
    "EmploymentType",
    "JobEnrichment",
    "JobPosting",
    "JobSource",
    "RemotePolicy",
    "Salary",
    "SalaryPeriod",
    "Seniority",
    "VisaSponsorship",
    "VisaSponsorshipStatus",
    "compute_content_hash",
]
