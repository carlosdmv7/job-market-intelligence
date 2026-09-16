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
    # the columns the app actually reads. The posting card is the reason this
    # list is long: it only renders once a row is selected, which AppTest
    # cannot drive, so a missing column there would reach a user first.
    for needed in (
        "country_code",
        "days_since_seen",
        "detected_language",
        "english_sufficient",
        "enriched_at",
        "enrichment_confidence",
        "enrichment_model",
        "enrichment_prompt_version",
        "is_active",
        "is_enriched",
        "is_recognised_sponsor",
        "is_target_role",
        "normalized_role",
        "relocation_support",
        "seniority",
        "sponsor_kvk",
        "technologies",
        "visa_confidence",
        "visa_evidence",
        "visa_reasoning",
        "visa_status",
        "working_languages",
    ):
        assert needed in cols


def test_the_app_never_opens_a_writable_connection(monkeypatch):
    """The read-only connection is guardrail #4, so it must not be optional.

    MotherDuck's free plan issues read/write tokens only, which makes the
    connection mode — not the token's scope — the thing standing between a
    public text-to-SQL agent and production. MotherDuck enforces it server-side
    (a CREATE over a read-only attachment is refused), but only if the app
    actually asks for read-only. It used to retry with read_only=False on any
    failure.
    """
    asked: list[bool] = []

    class _FakeConn:
        def execute(self, *_args, **_kwargs):
            return self

    class _FakeWarehouse:
        def __init__(self, _database, *, read_only=False, motherduck_token=None):
            asked.append(read_only)
            self.conn = _FakeConn()

    monkeypatch.setattr(db, "Warehouse", _FakeWarehouse)
    db._live_connection.clear()
    try:
        assert db._live_connection() is not None
    finally:
        db._live_connection.clear()
    assert asked == [True], f"the app asked for these read_only modes: {asked}"


def test_an_unreachable_warehouse_falls_back_to_demo_not_to_write_access(monkeypatch):
    asked: list[bool] = []

    class _RefusingWarehouse:
        def __init__(self, _database, *, read_only=False, motherduck_token=None):
            asked.append(read_only)
            raise RuntimeError("no network")

    monkeypatch.setattr(db, "Warehouse", _RefusingWarehouse)
    db._live_connection.clear()
    try:
        assert db._live_connection() is None
    finally:
        db._live_connection.clear()
    # One attempt, read-only. Never a second, writable one.
    assert asked == [True]
