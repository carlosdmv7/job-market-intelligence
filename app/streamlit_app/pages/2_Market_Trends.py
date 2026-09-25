"""Market Trends — where the roles are, which stacks they want, how that moves.

Scoped to open data roles by default, like every other list in the app, so a
number here and a number in Find Jobs cannot disagree. Closed roles stay
available behind the toggle: they are the only reason a history exists.

The charts answer three questions in order — *which country*, *which stack*,
*which direction* — because that is the order the decisions get made in.
"""

from __future__ import annotations

import altair as alt
import streamlit as st
from streamlit_app import ui
from streamlit_app.db import require_marts, run_df

ui.configure_page("Market Trends")
ui.page_header(
    title="Market Trends",
    subtitle=(
        "Which countries are hiring data people, which stacks they ask for, "
        "and how both move over time."
    ),
)

require_marts(
    "marts.FT_JOB_POSTING",
    missing="Connected, but no marts yet — run the pipeline, then `make dbt-build`.",
)

open_only = st.toggle(
    "Open data roles only",
    value=True,
    help=(
        "Off includes closed roles and non-data jobs. The history charts below "
        "always span every day on record — that is what they are for."
    ),
)
SCOPE = "is_target_role and is_active" if open_only else "true"
# The axis label has to follow the toggle. With it off these are every posting
# ever collected, and calling those "open roles" would be a false label on a
# real number — the exact failure this app is built to avoid.
UNIT = "open roles" if open_only else "all postings"

# --- 1 · which country -----------------------------------------------------
st.markdown("#### Where the roles are")

by_country = run_df(
    f"""
    select
        country_code,
        count(*)                                              as open_roles,
        count(distinct company_name)                          as companies,
        count(*) filter (where detected_language = 'en')      as written_in_english
    from marts.FT_JOB_POSTING
    where {SCOPE}
    group by 1 order by open_roles desc
    """
)
by_country["market"] = by_country["country_code"].map(ui.market_label)
# The language the ad is *written* in, not the LLM's read of whether English
# suffices. The LLM answer is better but exists for ~20% of rows, which meant
# Germany reported "0% English" off zero reads and Spain "67%" off three. This
# is deterministic and present on every row, so no sample guard is needed — and
# it is a strong proxy: of English-language postings the LLM has read it calls
# English sufficient 87% of the time, and of Dutch-language ones, never.
by_country["english_share"] = by_country["written_in_english"] / by_country["open_roles"]

c1, c2 = st.columns([3, 2], gap="large")
with c1:
    ui.show(ui.hbar(by_country, "market", "open_roles", value_title=UNIT))
with c2:
    ui.table(
        by_country[["market", "open_roles", "companies", "english_share"]],
        column_config={
            "market": st.column_config.TextColumn("Market"),
            "open_roles": st.column_config.NumberColumn("Roles", help=f"Counting {UNIT}."),
            "companies": st.column_config.NumberColumn("Companies"),
            "english_share": st.column_config.ProgressColumn(
                "Written in English",
                format="percent",
                min_value=0.0,
                max_value=1.0,
                help=(
                    "Share of this market's open roles whose ad is written in English. "
                    "Detected on ingest, so it covers every posting — and it is the "
                    "practical filter if you don't speak the local language."
                ),
            ),
        },
    )

top = by_country.iloc[0] if not by_country.empty else None
if top is not None:
    st.caption(
        f"**{top['market']} leads on volume** with {int(top['open_roles']):,} {UNIT}. "
        "Volume and language are different questions though — check the "
        "*Written in English* column before reading a big number as an opportunity."
    )

st.divider()

# --- 2 · which stack -------------------------------------------------------
st.markdown("#### Which stacks are hiring")
st.caption(
    "Extracted from the posting text by the LLM, so this covers the share of roles "
    "it has read so far — a sample of the market, not a census."
)

stacks = run_df(
    f"""
    select tech, count(*) as roles from (
        select unnest(technologies) as tech
        from marts.FT_JOB_POSTING where {SCOPE}
    ) group by 1 order by roles desc limit 15
    """
)
if stacks.empty:
    st.info("No technologies extracted yet — run `make enrich`.")
else:
    s1, s2 = st.columns([2, 3], gap="large")
    with s1:
        ui.show(ui.hbar(stacks, "tech", "roles", color=ui.ACCENT, value_title=UNIT))
    with s2:
        # Six series is the most a shared colour legend stays readable with.
        leaders = stacks.head(6)["tech"].tolist()
        placeholders = ", ".join("?" for _ in leaders)
        stack_trend = run_df(
            f"""
            select s.date_key, t.tech, count(distinct s.content_hash) as roles
            from marts.FT_JOB_SNAPSHOT_DAILY s
            join (
                select content_hash, unnest(technologies) as tech
                from marts.FT_JOB_POSTING
            ) t on t.content_hash = s.content_hash
            where s.is_target_role and t.tech in ({placeholders})
            group by 1, 2 order by 1
            """,
            tuple(leaders),
        )
        st.markdown("###### Demand for the leading stacks, day by day")
        if stack_trend["date_key"].nunique() < 2:
            st.info("Needs at least two snapshot days.")
        else:
            ui.show(
                alt.Chart(stack_trend)
                .mark_line(strokeWidth=2)
                .encode(
                    x=alt.X("date_key:T", title=None, axis=alt.Axis(grid=False)),
                    y=alt.Y("roles:Q", title="open roles", axis=alt.Axis(grid=True)),
                    color=alt.Color("tech:N", title=None, legend=alt.Legend(columns=3)),
                    tooltip=[
                        alt.Tooltip("date_key:T", title="day"),
                        alt.Tooltip("tech:N", title="stack"),
                        alt.Tooltip("roles:Q", title="open roles"),
                    ],
                )
                .properties(height=300)
            )

st.divider()

# --- 3 · which direction ---------------------------------------------------
st.markdown("#### How the market moves")
require_marts(
    "marts.FT_JOB_SNAPSHOT_DAILY",
    missing="Run the pipeline on a few different days to accumulate daily snapshots.",
    level="info",
)

daily = run_df(
    """
    select date_key, count(*) as open_roles
    from marts.FT_JOB_SNAPSHOT_DAILY
    where is_target_role
    group by date_key order by date_key
    """
)
if len(daily) < 2:
    st.info(
        f"Only {len(daily)} snapshot day so far — trends appear once the pipeline "
        "has run on several days."
    )
else:
    st.caption(
        f"{len(daily)} days on record. Each point is how many data roles were visible "
        "on the boards that day, so a dip is roles being filled faster than posted."
    )
    ui.show(
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
            y=alt.Y("open_roles:Q", title="open data roles", axis=alt.Axis(grid=True)),
            tooltip=[
                alt.Tooltip("date_key:T", title="day"),
                alt.Tooltip("open_roles:Q", title="open roles"),
            ],
        )
        .properties(height=240)
    )

    market_trend = run_df(
        """
        select date_key, country_code, count(*) as open_roles
        from marts.FT_JOB_SNAPSHOT_DAILY
        where is_target_role
        group by 1, 2 order by date_key
        """
    )
    market_trend["market"] = market_trend["country_code"].map(ui.market_label)
    st.markdown("###### By country")
    # No point markers: five series over 60+ days turned the lines into a
    # stipple where the trend used to be.
    ui.show(
        alt.Chart(market_trend)
        .mark_line(strokeWidth=2)
        .encode(
            x=alt.X("date_key:T", title=None, axis=alt.Axis(grid=False)),
            y=alt.Y("open_roles:Q", title="open data roles", axis=alt.Axis(grid=True)),
            color=alt.Color("market:N", title=None, legend=alt.Legend(columns=3)),
            tooltip=[
                alt.Tooltip("date_key:T", title="day"),
                "market:N",
                alt.Tooltip("open_roles:Q", title="open roles"),
            ],
        )
        .properties(height=280)
    )

st.divider()

# --- 4 · who -------------------------------------------------------------
st.markdown("#### Who is hiring most")
st.caption(f"By number of {UNIT}.")
companies = run_df(
    f"""
    select company_name, count(*) as open_roles
    from marts.FT_JOB_POSTING
    where {SCOPE} and company_name is not null
    group by 1 order by open_roles desc limit 12
    """
)
ui.show(ui.hbar(companies, "company_name", "open_roles", value_title=UNIT))

ui.page_footer()
