"""Text-to-SQL guard tests (no Streamlit, no LLM)."""

from __future__ import annotations

import pytest
from streamlit_app.agent import build_sql, clean_sql, enforce_limit, is_safe_select


def test_clean_sql_strips_fences():
    assert clean_sql("```sql\nselect 1\n```") == "select 1"
    assert clean_sql("select 1;") == "select 1"


@pytest.mark.parametrize(
    "sql",
    [
        "select * from marts.FT_JOB_POSTING",
        "WITH x as (select 1) select * from x",
        # replace() the scalar function is legitimate SQL, not a write.
        "select replace(company_name, ' B.V.', '') from marts.DT_COMPANY",
        # offset must not trip the "set" keyword.
        "select title from marts.FT_JOB_POSTING limit 10 offset 20",
    ],
)
def test_safe_selects_pass(sql):
    ok, _ = is_safe_select(sql)
    assert ok


@pytest.mark.parametrize(
    "sql",
    [
        "drop table marts.FT_JOB_POSTING",
        "delete from marts.FT_JOB_POSTING",
        "select 1; drop table x",
        "update marts.DT_COMPANY set company_name='x'",
        "attach 'evil.db'",
        "pragma database_list",
        # the write-flavoured REPLACEs stay rejected by other layers
        "create or replace table x as select 1",
        "insert or replace into x select 1",
        "with x as (select 1) insert into y select * from x",
    ],
)
def test_unsafe_rejected(sql):
    ok, reason = is_safe_select(sql)
    assert not ok and reason


def test_enforce_limit_adds_and_caps():
    assert "LIMIT 200" in enforce_limit("select * from marts.FT_JOB_POSTING")
    assert "LIMIT 500" in enforce_limit("select * from marts.FT_JOB_POSTING limit 10000")
    assert enforce_limit("select 1 limit 50").lower().endswith("limit 50")


class FakeProvider:
    model = "qwen2.5:7b"

    def __init__(self, sql):
        self._sql = sql

    def complete(self, *, system, user):
        return self._sql

    def classify(self, *, system, user, schema):  # unused here
        raise NotImplementedError


def test_build_sql_happy_path():
    p = FakeProvider(
        "```sql\nselect country_code, count(*) from marts.FT_JOB_POSTING group by 1\n```"
    )
    sql = build_sql("postings per country", p)
    assert sql.lower().startswith("select")
    assert "LIMIT" in sql


def test_build_sql_rejects_unsafe():
    with pytest.raises(ValueError):
        build_sql("nuke it", FakeProvider("drop table marts.FT_JOB_POSTING"))
