"""Cached warehouse access for the Streamlit app (read-only)."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from jmi_core.settings import get_settings
from jmi_core.warehouse import Warehouse


@st.cache_resource
def get_warehouse() -> Warehouse:
    s = get_settings()
    try:
        return Warehouse(s.duckdb_database, read_only=True, motherduck_token=s.motherduck_token)
    except Exception:
        # Some MotherDuck setups dislike read_only; fall back to a normal conn.
        return Warehouse(s.duckdb_database, motherduck_token=s.motherduck_token)


@st.cache_data(ttl=600, show_spinner=False)
def run_df(sql: str, params: tuple | None = None) -> pd.DataFrame:
    wh = get_warehouse()
    return wh.conn.execute(sql, list(params) if params else None).df()


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
