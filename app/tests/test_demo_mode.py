"""Demo mode: the app must run without a warehouse, and must say that it is."""

from __future__ import annotations

from streamlit_app import db


def test_demo_sample_is_committed():
    # The whole point is that a fresh clone works with no secrets. If the
    # parquet stops being committed, this is the test that notices.
    assert db.demo_available(), "app/demo/*.parquet is missing from the checkout"


def test_demo_connection_exposes_every_table_the_app_queries():
    conn = db._demo_connection.__wrapped__()
    for qualified in db._DEMO_TABLES.values():
        n = conn.execute(f"select count(*) from {qualified}").fetchone()[0]
        assert n >= 0, f"{qualified} is not queryable in demo mode"


def test_demo_facts_carry_the_columns_the_pages_select():
    conn = db._demo_connection.__wrapped__()
    cols = {
        r[0]
        for r in conn.execute(
            "select column_name from information_schema.columns where table_name = 'FT_JOB_POSTING'"
        ).fetchall()
    }
    # A sample with the wrong shape would fail at page load, not here, so pin
    # the columns the app actually reads.
    for needed in ("visa_status", "is_enriched", "is_recognised_sponsor", "country_code"):
        assert needed in cols
