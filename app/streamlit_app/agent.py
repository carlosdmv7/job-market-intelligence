"""Controlled text-to-SQL agent.

A question → a single read-only DuckDB SELECT over the ``marts`` schema, via the
same pluggable LLM provider as enrichment (Gemini's free tier by default,
so the whole app is 0€). Safety is
layered: a strict prompt, a SQL guard that parses the query with DuckDB's own
parser and lets it read only the marts tables (one SELECT; no file, network or
configuration access), an enforced LIMIT, and a read-only warehouse connection
with external access switched off.

This module is Streamlit-free so the guard logic is unit-testable.
"""

from __future__ import annotations

import json
import re
from typing import TYPE_CHECKING, Any, Literal

import duckdb

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
- ranking a list column ("most in demand", "top technologies"): unnest it and count,
  e.g. SELECT t, count(*) AS postings FROM marts.FT_JOB_POSTING, unnest(technologies)
  AS u(t) WHERE country_code = 'ES' GROUP BY t ORDER BY postings DESC LIMIT 20.
  Selecting the raw list column instead returns one row per posting, including the
  empty lists of postings whose stack was never extracted, which answers nothing.
- trends over time: group marts.FT_JOB_SNAPSHOT_DAILY by date_key.
- country_code is ISO alpha-2 (NL, SE, DE, ES, IE, ...); local per-country corpora come
  from adzuna (NL/DE/ES) and jobtech (SE); remote-first boards often have NULL country.
  IE rows (source = 'ats') come from ~30 employers' own career sites, not the whole
  Irish market: say so in any answer that compares Ireland with another country.
"""

SYSTEM_PROMPT = (
    "You are a senior analytics engineer. Translate the user's question into a SINGLE "
    "DuckDB SQL query.\n"
    "Rules:\n"
    "- Output ONLY the SQL, no prose, no markdown fences.\n"
    "- Read-only: a single SELECT (or WITH ... SELECT). Never modify data.\n"
    "- Use only the marts schema below; never reference raw or staging.\n"
    "- Always include a LIMIT (<= 500).\n"
    "- A question asking which, most, top or how many wants an AGGREGATE — group and "
    "count, ordered, not a dump of raw rows.\n\n" + MARTS_SCHEMA
)

#: The only relations a generated query may read. Everything else the
#: connection can reach — raw, staging, meta, information_schema, a file path,
#: a URL — is out of bounds, whatever the model was talked into writing.
ALLOWED_TABLES = frozenset(
    {"ft_job_posting", "ft_job_snapshot_daily", "dt_company", "dt_source", "dt_date"}
)

#: Table functions are how DuckDB reads the outside world (``read_text``,
#: ``read_csv``, ``glob``, ``duckdb_settings``, ``query``...), so they are
#: allow-listed, not deny-listed: a new one in a DuckDB release is rejected by
#: default instead of becoming a hole nobody noticed.
_ALLOWED_TABLE_FUNCTIONS = frozenset({"unnest"})

#: Shapes a FROM clause may take. Notably absent: SHOW_REF (``show tables``,
#: ``describe``, ``summarize``) and PIVOT.
_ALLOWED_TABLE_REFS = frozenset(
    {"BASE_TABLE", "JOIN", "SUBQUERY", "TABLE_FUNCTION", "EMPTY", "EXPRESSION_LIST"}
)

#: Scalar functions that read configuration or the environment rather than
#: data. MotherDuck's extension happens to answer ``<redacted>`` to
#: ``current_setting('motherduck_token')``; that is its courtesy, not a
#: property of this app, so nothing here leans on it and the list errs wide.
_FORBIDDEN_FUNCTIONS = frozenset(
    {
        "current_setting",
        "getenv",
        "getvariable",
        "query",
        "query_table",
        "glob",
        "sniff_csv",
        "which_secret",
        "write_log",
        "json_execute_serialized_sql",
        "sql_auto_complete",
    }
)
_FORBIDDEN_FUNCTION_PREFIXES = ("read_", "duckdb_", "pragma_", "md_", "parquet_", "http_")

#: A question is one sentence. The cap bounds what a visitor can spend of a
#: shared free-tier quota per call, and how much room an injection gets.
MAX_QUESTION_CHARS = 300


def clean_sql(raw: str) -> str:
    """Strip markdown fences / stray prose; keep the SQL body."""
    text = raw.strip()
    if "```" in text:
        # take the content of the first fenced block if present
        blocks = re.findall(r"```(?:sql)?\s*(.*?)```", text, re.DOTALL | re.IGNORECASE)
        if blocks:
            text = blocks[0].strip()
    return text.strip().rstrip(";").strip()


def _parse(sql: str) -> list[dict[str, Any]] | None:
    """The statements of ``sql`` as DuckDB's own syntax tree, or None.

    ``json_serialize_sql`` runs DuckDB's real parser and serialises nothing but
    SELECT statements, so anything else — DDL, DML, PRAGMA, COPY, ATTACH — is
    refused here by the engine that would have executed it, not by a keyword
    list that has to guess at its grammar. It parses only: nothing is planned
    or run, and the throwaway in-memory connection has no warehouse attached.
    """
    conn = duckdb.connect(":memory:")
    try:
        row = conn.execute("select json_serialize_sql(?)", [sql]).fetchone()
    except duckdb.Error:
        return None
    finally:
        conn.close()
    tree = json.loads(row[0]) if row else {}
    if tree.get("error"):
        return None
    return list(tree.get("statements") or [])


def _violation(node: Any, ctes: frozenset[str]) -> str:
    """First reason a syntax-tree node is out of bounds, or "" when it is fine."""
    if isinstance(node, list):
        return next((r for r in (_violation(child, ctes) for child in node) if r), "")
    if not isinstance(node, dict):
        return ""

    # A table reference is the node with an alias and a sample clause that is
    # neither an expression ("class") nor a query node ("modifiers").
    if "sample" in node and "alias" in node and not {"class", "modifiers"} & node.keys():
        kind = node.get("type")
        if kind not in _ALLOWED_TABLE_REFS:
            return f"unsupported FROM clause: {kind}"
        if kind == "BASE_TABLE":
            schema = (node.get("schema_name") or "").lower()
            table = (node.get("table_name") or "").lower()
            if node.get("catalog_name"):
                return "queries may not name another database"
            in_marts = schema == "marts" and table in ALLOWED_TABLES
            is_cte = not schema and table in ctes
            if not (in_marts or is_cte):
                shown = f"{schema}.{table}" if schema else table
                return f"only the marts tables can be queried, not {shown!r}"
        if kind == "TABLE_FUNCTION":
            name = ((node.get("function") or {}).get("function_name") or "").lower()
            if name not in _ALLOWED_TABLE_FUNCTIONS:
                return f"table function not allowed: {name or 'unknown'}"

    if node.get("class") == "FUNCTION":
        name = (node.get("function_name") or "").lower()
        if node.get("schema") or node.get("catalog"):
            return f"qualified function call not allowed: {name}"
        if name in _FORBIDDEN_FUNCTIONS or name.startswith(_FORBIDDEN_FUNCTION_PREFIXES):
            return f"function not allowed: {name}"

    return next((r for r in (_violation(child, ctes) for child in node.values()) if r), "")


def _cte_names(node: Any) -> set[str]:
    names: set[str] = set()
    if isinstance(node, list):
        for child in node:
            names |= _cte_names(child)
    elif isinstance(node, dict):
        for entry in (node.get("cte_map") or {}).get("map") or []:
            names.add(str(entry.get("key", "")).lower())
        for child in node.values():
            names |= _cte_names(child)
    return names


def is_safe_select(sql: str) -> tuple[bool, str]:
    """Return (ok, reason). Defense-in-depth on top of a locked-down connection.

    This used to be a keyword blocklist over the query text, and it had the
    weakness every such list has: it knew which *statements* write, and nothing
    about what a SELECT can read. ``select content from read_text('.env')`` is a
    single read-only SELECT, and run on this app's connection it returned the
    warehouse token (ADR 0012). So the query is parsed and its tree checked
    against what it may touch: the five marts tables, its own CTEs, ``unnest``,
    and no function that reads configuration or files.
    """
    s = sql.strip().rstrip(";").strip()
    if not s:
        return False, "empty query"
    low = s.lower()
    if not (low.startswith("select") or low.startswith("with")):
        return False, "query must start with SELECT or WITH"
    statements = _parse(s)
    if statements is None:
        return False, "not a read-only SELECT that DuckDB can parse"
    if len(statements) != 1:
        return False, "only a single statement is allowed"
    reason = _violation(statements, frozenset(_cte_names(statements)))
    return (False, reason) if reason else (True, "")


def _top_level_limit(sql: str) -> int | Literal["dynamic"] | None:
    """The outermost LIMIT: its row count, None if absent, "dynamic" otherwise."""
    statements = _parse(sql)
    if not statements:
        return "dynamic"
    for modifier in (statements[0].get("node") or {}).get("modifiers") or []:
        if modifier.get("type") == "LIMIT_MODIFIER":
            value = ((modifier.get("limit") or {}).get("value") or {}).get("value")
            if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
                return value
            return "dynamic"
        if modifier.get("type") == "LIMIT_PERCENT_MODIFIER":
            return "dynamic"
    return None


def enforce_limit(sql: str, default: int = 200, hard_cap: int = 500) -> str:
    """Ensure the *outermost* query has a LIMIT that never exceeds hard_cap.

    Read off the syntax tree, not the text: a regex took the first ``limit N``
    it found, so a LIMIT inside a subquery counted as the query's own and the
    outer SELECT ran unbounded. A limit that is too large, or not a plain
    number, is capped by wrapping the query rather than by rewriting it.
    """
    s = sql.strip().rstrip(";").strip()
    limit = _top_level_limit(s)
    if limit is None:
        return f"{s}\nLIMIT {default}"
    if isinstance(limit, int) and limit <= hard_cap:
        return s
    return f"SELECT * FROM (\n{s}\n) AS capped\nLIMIT {hard_cap}"


def build_sql(question: str, provider: LLMProvider) -> str:
    """Generate, clean, validate, and limit a SQL query for a question."""
    question = question.strip()
    if len(question) > MAX_QUESTION_CHARS:
        raise ValueError(f"Question too long (max {MAX_QUESTION_CHARS} characters).")
    raw = provider.complete(system=SYSTEM_PROMPT, user=question)
    sql = clean_sql(raw)
    ok, reason = is_safe_select(sql)
    if not ok:
        raise ValueError(f"Generated query rejected ({reason}):\n{sql}")
    return enforce_limit(sql)
