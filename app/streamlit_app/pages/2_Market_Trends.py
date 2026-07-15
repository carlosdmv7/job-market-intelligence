"""Market composition + temporal trends from the marts."""

from __future__ import annotations

import altair as alt
import streamlit as st
from streamlit_app import ui
from streamlit_app.db import require_marts, run_df

st.set_page_config(page_title="Market Trends", page_icon="📈", layout="wide")
st.title("📈 Market Trends")
st.caption("What the EU tech market looks like right now, and how it moves over time.")

require_marts(
    "marts.FT_JOB_POSTING",
    missing="Connected, but no marts yet — run the pipeline, then `make dbt-build`.",
)

# --- current composition ---------------------------------------------------
st.markdown("##### Top hiring companies")
st.caption("Green = on the IND recognised-sponsor register (can sponsor a NL visa).")
comp = run_df(
    """
    select company_name,
           max(cast(is_recognised_sponsor as int)) as sponsor,
           count(*) as postings
    from marts.FT_JOB_POSTING
    where company_name is not null
    group by 1 order by postings desc limit 15
    """
)
comp["kind"] = comp["sponsor"].map({1: "Recognised sponsor", 0: "Other"})
companies = (
    alt.Chart(comp)
    .mark_bar()
    .encode(
        y=alt.Y("company_name:N", sort="-x", title=None, axis=alt.Axis(labelLimit=220)),
        x=alt.X("postings:Q", title="postings", axis=alt.Axis(grid=True, tickCount=4)),
        color=alt.Color(
            "kind:N",
            scale=alt.Scale(domain=["Recognised sponsor", "Other"], range=[ui.GOOD, ui.MUTED]),
            title=None,
        ),
        tooltip=[
            alt.Tooltip("company_name:N", title="company"),
            alt.Tooltip("postings:Q"),
            alt.Tooltip("kind:N", title="sponsor"),
        ],
    )
    .properties(height=max(160, len(comp) * 30 + 12))
)
ui.show(companies)

left, right = st.columns(2, gap="large")
with left:
    st.markdown("##### Postings by source")
    src = run_df(
        "select source, count(*) as postings from marts.FT_JOB_POSTING group by 1 order by 2 desc"
    )
    ui.show(ui.hbar(src, "source", "postings", value_title="postings"))
with right:
    st.markdown("##### Jobs by location")
    loc = run_df(
        "select case when country_code is null then 'Remote / global' else country_code end "
        "as location, count(*) as n from marts.FT_JOB_POSTING group by 1 order by n desc"
    )
    ui.show(ui.hbar(loc, "location", "n", value_title="postings"))

# --- temporal (needs accumulated daily snapshots) --------------------------
st.divider()
st.markdown("##### Over time")
require_marts(
    "marts.FT_JOB_SNAPSHOT_DAILY",
    missing="Run the pipeline on a few different days to accumulate daily snapshots.",
    level="info",
)

daily = run_df(
    "select date_key, count(*) as active_postings "
    "from marts.FT_JOB_SNAPSHOT_DAILY group by date_key order by date_key"
)
if len(daily) < 2:
    st.info(
        f"Only {len(daily)} snapshot day so far — trends appear once the pipeline "
        "has run on multiple days (`make ingest-all` daily)."
    )
else:
    line = (
        alt.Chart(daily)
        .mark_area(
            line={"color": ui.BLUE, "strokeWidth": 2},
            color=alt.Gradient(
                gradient="linear",
                stops=[
                    alt.GradientStop(color="#ffffff", offset=0),
                    alt.GradientStop(color=ui.BLUE, offset=1),
                ],
                x1=1,
                x2=1,
                y1=1,
                y2=0,
            ),
            opacity=0.25,
        )
        .encode(
            x=alt.X("date_key:T", title=None, axis=alt.Axis(grid=False)),
            y=alt.Y("active_postings:Q", title="active postings", axis=alt.Axis(grid=True)),
            tooltip=[
                alt.Tooltip("date_key:T", title="day"),
                alt.Tooltip("active_postings:Q", title="active"),
            ],
        )
        .properties(height=260)
    )
    ui.show(line)

    by_source = run_df(
        "select date_key, source, count(*) as n "
        "from marts.FT_JOB_SNAPSHOT_DAILY group by date_key, source order by date_key"
    )
    st.markdown("##### Active postings by source over time")
    multi = (
        alt.Chart(by_source)
        .mark_line(strokeWidth=2, point=True)
        .encode(
            x=alt.X("date_key:T", title=None, axis=alt.Axis(grid=False)),
            y=alt.Y("n:Q", title="active postings", axis=alt.Axis(grid=True)),
            color=alt.Color("source:N", title=None),
            tooltip=[
                alt.Tooltip("date_key:T", title="day"),
                "source:N",
                alt.Tooltip("n:Q", title="active"),
            ],
        )
        .properties(height=260)
    )
    ui.show(multi)
