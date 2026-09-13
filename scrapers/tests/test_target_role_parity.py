"""The SQL macro and the Python matcher must agree.

``jmi_is_target_role`` (dbt) and ``is_target_role`` (jmi_scrapers) express the
same scope decision on two sides of the stack: the scrapers apply it at ingest,
the mart applies it to rows that landed before the filter existed. Two copies
of a regex drift, and the drift would be invisible — the app would quietly show
a different corpus than the scrapers collect.

So this pins them together. Offline: the SQL side runs on an in-memory DuckDB,
no warehouse needed. Verified against all 12,773 real titles when written; the
fixtures below are the cases that actually distinguish the two.
"""

from __future__ import annotations

import re
from pathlib import Path

import duckdb
import pytest

from jmi_core.roles import is_target_role

_MACRO = Path(__file__).resolve().parents[2] / "dbt" / "jmi" / "macros" / "jmi_is_target_role.sql"

TITLES = [
    # kept
    "Data Engineer",
    "Senior Data Engineer (m/w/d)",
    "Analytics Engineer",
    "Senior Data Analyst, People Analytics",
    "Machine Learning Engineer",
    "Multimodal ML Engineer",
    "MLOps Specialist",
    "AI Engineer (m/w/d)",
    "Senior AI/ML Consultant",
    "Senior BI Developer",
    "Working Student - Market & Business Intelligence (f/m/x)",
    "Data Platform Engineer",
    "Big Data Architect",
    "LLM Research Engineer",
    "ETL Developer",
    # dropped
    "Hotel Executive Assistant Manager",
    "Steuerberater (m/w/d) in Wiehl",
    "Senior Sales Executive (m/w/d)",
    "Transactional Financial Controller",
    "Abteilungsleiter / Department Manager (m/w/d)",
    "Senior Corporate Infrastructure Engineer",
    "Graduate New Business Executive at SetSales",
    # the regression: an early pattern anchored only the front of each term and
    # matched "BI" inside "Bildung", re-admitting the noise it removes.
    "Werkstudent (m/w/d) Redaktion Bildung.Table",
    "Bildungsreferent (m/w/d)",
    "Senior Mobile Engineer - Retail",
]


def _sql_pattern() -> str:
    """The regex literal out of the dbt macro, so the test reads the real file."""
    text = _MACRO.read_text(encoding="utf-8")
    match = re.search(r"'(\\b\(data\|.*?)'", text, re.S)
    assert match, "could not find the pattern literal in jmi_is_target_role.sql"
    return match.group(1)


@pytest.mark.parametrize("title", TITLES)
def test_sql_macro_and_python_matcher_agree(title):
    conn = duckdb.connect()
    sql_says = conn.execute(
        "select regexp_matches(lower(coalesce(?, '')), ?)", [title, _sql_pattern()]
    ).fetchone()[0]
    assert bool(sql_says) is is_target_role(title), title
