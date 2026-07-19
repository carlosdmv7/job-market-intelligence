"""Controlled text-to-SQL agent.

A question → a single read-only DuckDB SELECT over the ``marts`` schema, via the
same pluggable LLM provider as enrichment (Ollama by default → 0€). Safety is
layered: a strict prompt, a SQL guard (SELECT-only, no DDL/DML, single
statement), an enforced LIMIT, and a read-only warehouse connection.

This module is Streamlit-free so the guard logic is unit-testable.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from jmi_enrichment.providers import LLMProvider

# Compact schema handed to the model. Keep in sync with the marts models.
MARTS_SCHEMA = """\
Schema "marts" (DuckDB). Use ONLY these tables/columns.

marts.FT_JOB_POSTING  -- one row per deduplicated current posting
  title, company_name, country_code, location_raw, source, source_url,
  posted_at (timestamp), salary_raw, is_remote_raw (bool), source_count (int),
  normalized_role, role_family, seniority, employment_type, remote_policy,
  technologies (VARCHAR[]), visa_status, visa_confidence (0..1), visa_evidence,
  visa_reasoning, is_visa_sponsor (bool), requires_local_language (bool),
  working_languages (VARCHAR[]), english_sufficient (bool), relocation_support (bool),
  enrichment_confidence (0..1), is_enriched (bool),
  enrichment_model, enrichment_prompt_version, enriched_at (timestamp),
  is_recognised_sponsor (bool)  -- company is on the official IND register (NL visa sponsor)
  sponsor_kvk                   -- Dutch Chamber of Commerce number proving it

marts.FT_JOB_SNAPSHOT_DAILY  -- one row per source posting per observed day
  date_key (date), source, company_name, country_code, title,
  is_first_seen (bool), is_last_seen (bool), days_since_first_seen (int)

marts.DT_COMPANY (company_name, country_code, posting_count, first_posting_at,
                  last_seen_at, is_recognised_sponsor (bool), sponsor_kvk)
marts.DT_SOURCE  (source, primary_country, source_type, is_remote_first)
marts.DT_DATE    (date_key, year, month, day_of_month, year_month, day_of_week, is_weekend)

Tips:
- Visa sponsorship, strongest signal: WHERE is_recognised_sponsor — deterministic match
  against the official IND register, verifiable via sponsor_kvk. The LLM's read of the
  posting text (is_visa_sponsor, visa_status='explicit_yes') is a secondary signal.
- array membership: list_contains(technologies, 'dbt').
- trends over time: group marts.FT_JOB_SNAPSHOT_DAILY by date_key.
- country_code is ISO alpha-2 (NL, SE, DE, ES, ...); local per-country corpora come
  from adzuna (NL/DE/ES) and jobtech (SE); remote-first boards often have NULL country.
"""

SYSTEM_PROMPT = (
    "You are a senior analytics engineer. Translate the user's question into a SINGLE "
    "DuckDB SQL query.\n"
    "Rules:\n"
    "- Output ONLY the SQL, no prose, no markdown fences.\n"
    "- Read-only: a single SELECT (or WITH ... SELECT). Never modify data.\n"
    "- Use only the marts schema below; never reference raw or staging.\n"
    "- Always include a LIMIT (<= 500).\n\n" + MARTS_SCHEMA
)

# "replace" is deliberately absent: as a bare word it is the legitimate scalar
# function replace(col, a, b); its dangerous forms (CREATE OR REPLACE,
# INSERT OR REPLACE) are already rejected twice — by the SELECT/WITH-only
# check and by the "create"/"insert" keywords below.
_FORBIDDEN = (
    "insert",
    "update",
    "delete",
    "drop",
    "create",
    "alter",
    "attach",
    "detach",
    "copy",
    "pragma",
    "install",
    "load",
    "export",
    "truncate",
    "merge",
    "grant",
    "revoke",
    "call",
    "set",
)


def clean_sql(raw: str) -> str:
    """Strip markdown fences / stray prose; keep the SQL body."""
    text = raw.strip()
    if "```" in text:
        # take the content of the first fenced block if present
        blocks = re.findall(r"```(?:sql)?\s*(.*?)```", text, re.DOTALL | re.IGNORECASE)
        if blocks:
            text = blocks[0].strip()
    return text.strip().rstrip(";").strip()


def is_safe_select(sql: str) -> tuple[bool, str]:
    """Return (ok, reason). Defense-in-depth on top of a read-only connection."""
    s = sql.strip().rstrip(";").strip()
    if not s:
        return False, "empty query"
    if ";" in s:
        return False, "only a single statement is allowed"
    low = s.lower()
    if not (low.startswith("select") or low.startswith("with")):
        return False, "query must start with SELECT or WITH"
    for kw in _FORBIDDEN:
        if re.search(rf"\b{kw}\b", low):
            return False, f"forbidden keyword: {kw}"
    return True, ""


def enforce_limit(sql: str, default: int = 200, hard_cap: int = 500) -> str:
    """Ensure a LIMIT exists and never exceeds hard_cap."""
    s = sql.strip().rstrip(";")
    match = re.search(r"\blimit\s+(\d+)\b", s, re.IGNORECASE)
    if match:
        if int(match.group(1)) > hard_cap:
            s = re.sub(r"\blimit\s+\d+\b", f"LIMIT {hard_cap}", s, flags=re.IGNORECASE)
        return s
    return f"{s}\nLIMIT {default}"


def build_sql(question: str, provider: LLMProvider) -> str:
    """Generate, clean, validate, and limit a SQL query for a question."""
    raw = provider.complete(system=SYSTEM_PROMPT, user=question.strip())
    sql = clean_sql(raw)
    ok, reason = is_safe_select(sql)
    if not ok:
        raise ValueError(f"Generated query rejected ({reason}):\n{sql}")
    return enforce_limit(sql)
