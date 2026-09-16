"""Cached warehouse access for the Streamlit app (read-only).

Two modes, and the app always says which one it is in:

* **live** — MotherDuck, the real warehouse the pipeline writes to;
* **demo** — a committed parquet sample (``app/demo/``), used when no
  warehouse is reachable, so a fresh clone runs with no secrets and no
  network.

Demo mode is a fallback, never a silent substitute. A dashboard that shows a
frozen sample as if it were live data is the exact failure this project argues
against everywhere else, so :func:`is_demo` is surfaced in the UI.
"""

from __future__ import annotations

import os
from pathlib import Path

import duckdb
import pandas as pd
import streamlit as st

from jmi_core.settings import get_settings
from jmi_core.warehouse import Warehouse

DEMO_DIR = Path(__file__).resolve().parent.parent / "demo"

#: parquet file (without extension) -> the qualified name the app queries.
_DEMO_TABLES = {
    "FT_JOB_POSTING": "marts.FT_JOB_POSTING",
    "DT_COMPANY": "marts.DT_COMPANY",
    "DT_SOURCE": "marts.DT_SOURCE",
    "DT_DATE": "marts.DT_DATE",
    "FT_JOB_SNAPSHOT_DAILY": "marts.FT_JOB_SNAPSHOT_DAILY",
    "pipeline_run": "meta.pipeline_run",
}


def demo_available() -> bool:
    return DEMO_DIR.is_dir() and (DEMO_DIR / "FT_JOB_POSTING.parquet").exists()


@st.cache_resource
def _demo_connection() -> duckdb.DuckDBPyConnection:
    """In-memory DuckDB with views over the committed parquet sample.

    Views, not tables: the parquet stays on disk and nothing is copied into
    memory until a query actually touches it.
    """
    conn = duckdb.connect(":memory:")
    for schema in ("marts", "meta"):
        conn.execute(f"create schema if not exists {schema}")
    for stem, qualified in _DEMO_TABLES.items():
        path = DEMO_DIR / f"{stem}.parquet"
        if path.exists():
            conn.execute(
                f"create or replace view {qualified} as select * from read_parquet('{path}')"
            )
    return conn


def _bridge_streamlit_secrets() -> None:
    """Copy Streamlit's secrets into the environment before Settings is read.

    A deployed app has no ``.env``; on Streamlit Community Cloud the token lives
    in the app's **Secrets** panel, which is outside the repo and therefore
    never committed. Streamlit does also export top-level secrets as environment
    variables, so this is usually redundant — but "usually" is a bad property
    for the one thing standing between a public app and its data, and the
    failure mode is a deployed app that silently falls back to demo mode.

    Only fills gaps: a real environment variable always wins.
    """
    try:
        secrets = st.secrets
    except Exception:
        return  # no secrets file — local runs use .env
    for key in ("motherduck_token", "JMI_DUCKDB_DATABASE", "GEMINI_API_KEY"):
        try:
            value = secrets[key]
        except Exception:
            continue
        os.environ.setdefault(key, str(value))


_bridge_streamlit_secrets()


@st.cache_resource
def _live_connection() -> duckdb.DuckDBPyConnection | None:
    """The real warehouse, read-only, or ``None`` when it cannot be reached.

    **Read-only is not negotiable and there is no fallback.** This used to try
    ``read_only=True`` and then retry with ``read_only=False`` on any failure,
    on the theory that some MotherDuck setups dislike read-only connections.
    They don't — a read-only connection to MotherDuck works and the *server*
    enforces it, refusing a CREATE with "cannot execute statement of type
    CREATE on a database attached in read-only mode". So the fallback protected
    against nothing, and what it risked was everything: this app is public, it
    serves a text-to-SQL agent, and MotherDuck's free plan issues read/write
    tokens only. One transient error on the first attempt and a stranger's SQL
    would have been running against production with write access, with the app
    still claiming a read-only connection as its fourth guardrail.

    Losing the connection entirely is the better failure: it lands in demo
    mode, which says so on every page.
    """
    s = get_settings()
    try:
        wh = Warehouse(s.duckdb_database, read_only=True, motherduck_token=s.motherduck_token)
        # Connecting can succeed lazily; force a real round trip so a bad
        # token fails here rather than on the first page that queries.
        wh.conn.execute("select 1")
        return wh.conn
    except Exception:
        return None


def is_demo() -> bool:
    """True when the app is serving the committed sample instead of the warehouse."""
    return _live_connection() is None and demo_available()


def _connection() -> duckdb.DuckDBPyConnection:
    live = _live_connection()
    if live is not None:
        return live
    if demo_available():
        return _demo_connection()
    raise WarehouseUnreachable(
        "no warehouse and no demo sample: set motherduck_token, or run "
        "`uv run python -m jmi_flows.export_demo`"
    )


@st.cache_data(ttl=600, show_spinner=False)
def run_df(sql: str, params: tuple | None = None) -> pd.DataFrame:
    return _connection().execute(sql, list(params) if params else None).df()


class WarehouseUnreachable(RuntimeError):
    """The warehouse can't be queried at all (missing/invalid token, network)."""


def table_exists(qualified: str) -> bool:
    """True/False only when the catalog was actually readable.

    A connection failure is *not* an absent table, so it raises instead of
    returning False — otherwise a bad token renders as "no data yet" and sends
    people off to re-run a pipeline that was never the problem.
    """
    schema, _, name = qualified.partition(".")
    try:
        df = run_df(
            "select 1 from information_schema.tables where table_schema=? and table_name=?",
            (schema, name),
        )
    except Exception as exc:
        raise WarehouseUnreachable(str(exc)) from exc
    return not df.empty


def require_marts(*qualified: str, missing: str, level: str = "warning") -> None:
    """Halt the page with an accurate diagnosis when the data isn't queryable."""
    try:
        absent = [q for q in qualified if not table_exists(q)]
    except WarehouseUnreachable as exc:
        st.error(
            "**Can't reach the warehouse.** This is a connection problem, not missing data.\n\n"
            "A deployed app doesn't read `.env` — set `motherduck_token` and "
            "`JMI_DUCKDB_DATABASE` in the app's **Secrets**."
        )
        st.caption(f"The database driver said: {exc}")
        st.stop()
    if absent:
        getattr(st, level)(missing)
        st.stop()
