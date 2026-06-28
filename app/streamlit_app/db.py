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


def table_exists(qualified: str) -> bool:
    schema, _, name = qualified.partition(".")
    try:
        df = run_df(
            "select 1 from information_schema.tables where table_schema=? and table_name=?",
            (schema, name),
        )
        return not df.empty
    except Exception:
        return False
