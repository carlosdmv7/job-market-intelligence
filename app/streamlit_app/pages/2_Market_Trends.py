"""Market composition + temporal trends from the marts."""

from __future__ import annotations

import altair as alt
import streamlit as st
from streamlit_app import ui
from streamlit_app.db import require_marts, run_df

ui.configure_page("Market Trends")
ui.page_header(
    title="📈 Market Trends",
    subtitle=(
        "What the tracked markets (🇳🇱 🇸🇪 🇩🇪 🇪🇸 + remote boards) look like right now, "
        "and how they move over time."
    ),
)

require_marts(
    "marts.FT_JOB_POSTING",
    missing="Connected, but no marts yet — run the pipeline, then `make dbt-build`.",
)

# --- current composition ---------------------------------------------------
st.markdown("##### Top hiring companies")
st.caption(
    "Colour is the visa signal: a deterministic IND register match, a text-only signal "
    "from the LLM, or a posting the LLM has not read yet."
)
comp = run_df(
    f"""
    with ranked as (
        select company_name, count(*) as postings
        from marts.FT_JOB_POSTING
        where company_name is not null
        group by 1 order by postings desc limit 15
    )
    select
        f.company_name,
        {ui.SPONSORSHIP_SQL} as sponsorship,
        count(*) as postings
    from marts.FT_JOB_POSTING f
    join ranked r on r.company_name = f.company_name
    group by 1, 2
    """
)
ui.show(ui.sponsorship_bar(comp, "company_name", "postings", value_title="postings"))

left, right = st.columns(2, gap="large")
with left:
    st.markdown("##### Postings by source")
    src = run_df(
        "select source, count(*) as postings from marts.FT_JOB_POSTING group by 1 order by 2 desc"
    )
    ui.show(ui.hbar(src, "source", "postings", value_title="postings"))
with right:
    st.markdown("##### Jobs by market")
    loc = run_df(
        "select country_code, count(*) as n from marts.FT_JOB_POSTING group by 1 order by n desc"
    )
    loc["market"] = loc["country_code"].map(ui.market_label)
    ui.show(ui.hbar(loc, "market", "n", value_title="postings"))

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
            line={"color": ui.PRIMARY, "strokeWidth": 2},
            color=alt.Gradient(
                gradient="linear",
                stops=[
                    alt.GradientStop(color=ui.SURFACE_COLOR, offset=0),
                    alt.GradientStop(color=ui.PRIMARY, offset=1),
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

    t1, t2 = st.columns(2, gap="large")
    with t1:
        by_market = run_df(
            "select date_key, country_code, count(*) as n "
            "from marts.FT_JOB_SNAPSHOT_DAILY group by 1, 2 order by date_key"
        )
        by_market["market"] = by_market["country_code"].map(ui.market_label)
        st.markdown("##### Active postings by market over time")
        ui.show(
            alt.Chart(by_market)
            .mark_line(strokeWidth=2, point=True)
            .encode(
                x=alt.X("date_key:T", title=None, axis=alt.Axis(grid=False)),
                y=alt.Y("n:Q", title="active postings", axis=alt.Axis(grid=True)),
                color=alt.Color("market:N", title=None),
                tooltip=[
                    alt.Tooltip("date_key:T", title="day"),
                    "market:N",
                    alt.Tooltip("n:Q", title="active"),
                ],
            )
            .properties(height=260)
        )
    with t2:
        by_source = run_df(
            "select date_key, source, count(*) as n "
            "from marts.FT_JOB_SNAPSHOT_DAILY group by date_key, source order by date_key"
        )
        st.markdown("##### Active postings by source over time")
        ui.show(
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

ui.page_footer()
