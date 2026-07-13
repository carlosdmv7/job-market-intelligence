"""Temporal trends from the daily snapshot fact."""

from __future__ import annotations

import streamlit as st
from streamlit_app.db import run_df, table_exists

st.set_page_config(page_title="Market Trends", page_icon="📈", layout="wide")
st.title("📈 Market Trends")

if not table_exists("marts.FT_JOB_SNAPSHOT_DAILY"):
    st.warning("Run the pipeline a few days + `make dbt-build` to accumulate snapshots.")
    st.stop()

st.subheader("Active postings per day")
st.line_chart(
    run_df(
        "select date_key, count(*) as active_postings "
        "from marts.FT_JOB_SNAPSHOT_DAILY group by date_key order by date_key"
    ).set_index("date_key")
)

st.subheader("New postings per day (first seen)")
st.bar_chart(
    run_df(
        "select date_key, count(*) as new_postings "
        "from marts.FT_JOB_SNAPSHOT_DAILY where is_first_seen group by date_key order by date_key"
    ).set_index("date_key")
)

st.subheader("Postings by source over time")
pivot = run_df(
    "select date_key, source, count(*) as n "
    "from marts.FT_JOB_SNAPSHOT_DAILY group by date_key, source order by date_key"
)
if not pivot.empty:
    st.line_chart(pivot.pivot(index="date_key", columns="source", values="n").fillna(0))

st.subheader("Top hiring companies")
st.dataframe(
    run_df(
        "select company_name, count(distinct source_job_id) as postings "
        "from marts.FT_JOB_SNAPSHOT_DAILY where is_last_seen group by 1 order by postings desc limit 20"
    ),
    use_container_width=True,
    hide_index=True,
)
