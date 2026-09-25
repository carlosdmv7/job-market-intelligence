"""Market Trends — where the roles are, which stacks they want, how that moves.

Scoped to open data roles by default, like every other list in the app, so a
number here and a number in Find Jobs cannot disagree. Closed roles stay
available behind the toggle: they are the only reason a history exists.

The charts answer three questions in order — *which country*, *which stack*,
*which direction* — because that is the order the decisions get made in.
"""

from __future__ import annotations

import altair as alt
import pandas as pd
import streamlit as st
from streamlit_app import ui
from streamlit_app.db import require_marts, run_df

from jmi_core.settings import get_settings

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

# Days whose sweep can be read as the market. Two kinds of day cannot: the
# ramp-up before the first full sweep, when sources were still being added and
# the count climbed from zero, and partial sweeps, when the pipeline tracked far
# fewer postings than usual. Both drew steps and dips that the captions read as
# roles being posted or filled; they were the scraper. Same 85% rule as the
# Overview's daily chart.
PARTIAL_SWEEP = 0.85
try:
    _sweeps = run_df(
        """
        select date_key, count(*) as tracked
        from marts.FT_JOB_SNAPSHOT_DAILY where is_target_role
        group by 1 order by 1
        """
    )
except Exception:  # no snapshot table yet: section 3 says so, the rest has nothing to filter
    _sweeps = pd.DataFrame({"date_key": [], "tracked": []})
_full = _sweeps["tracked"] >= PARTIAL_SWEEP * _sweeps["tracked"].median()
_first_full = _sweeps.loc[_full, "date_key"].min() if _full.any() else None
FULL_SWEEP_DAYS = set(_sweeps.loc[_full & (_sweeps["date_key"] >= _first_full), "date_key"])
LEFT_OUT = len(_sweeps) - len(FULL_SWEEP_DAYS)


def full_sweeps_only(df: pd.DataFrame) -> pd.DataFrame:
    """Rows of a daily series on days whose sweep reads as the market."""
    return df[df["date_key"].isin(FULL_SWEEP_DAYS)]


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

# Each Adzuna market (ES, DE, NL) is swept up to a fixed number of postings a
# day — JMI_SCRAPE_MAX_POSTINGS, 200 — so their counts sit at that ceiling and
# say how much was fetched, not how big the market is. "Spain leads on volume"
# used to be printed off exactly that ceiling.
SWEEP_CAP = get_settings().scrape_max_postings
st.caption(
    f"**These are sampled, not total, volumes.** Spain, Germany and the "
    f"Netherlands are each read up to {SWEEP_CAP} postings a day, so their counts "
    "mostly show that ceiling; Sweden stays under it. Compare the "
    "*Written in English* share, which holds whatever the sample size."
)

st.divider()

# --- 2 · which stack -------------------------------------------------------
st.markdown("#### Which stacks are hiring")
st.caption(
    "Each market weighs the same: a technology's share of every stack mention in a "
    "market, averaged across markets. Raw counts ranked Sweden — its board carries "
    "full postings, where the LLM finds ~7 technologies, against ~2 in the snippets "
    "the other markets give — so they are not used here."
)

# Markets with too few read postings to have a mix (remote, today) sit out of
# the average rather than swinging it on a handful of roles.
MIN_READ_PER_MARKET = 20
stacks = run_df(
    f"""
    with read as (
        select country_code, technologies from marts.FT_JOB_POSTING
        where {SCOPE} and country_code is not null and len(technologies) > 0
    ),
    markets as (
        select country_code from read group by 1 having count(*) >= {MIN_READ_PER_MARKET}
    ),
    mix as (
        select country_code, tech,
               count(*) * 1.0 / sum(count(*)) over (partition by country_code) as share
        from (select country_code, unnest(technologies) as tech from read)
        where country_code in (select country_code from markets)
        group by 1, 2
    )
    select tech,
           round(100 * sum(share) / (select count(*) from markets), 1) as pct
    from mix group by 1 order by pct desc limit 15
    """
)
if stacks.empty:
    st.info("No technologies extracted yet — run `make enrich`.")
else:
    s1, s2 = st.columns([2, 3], gap="large")
    with s1:
        ui.show(
            ui.hbar(
                stacks,
                "tech",
                "pct",
                color=ui.PRIMARY,
                value_title="% of stack mentions, average market",
            )
        )
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
        stack_trend = full_sweeps_only(stack_trend)
        st.markdown("###### Demand for the leading stacks, day by day")
        st.caption(
            "Open roles naming each stack. Counts lean towards Sweden's full "
            "postings, so read each line's direction, not its level."
        )
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
daily = full_sweeps_only(daily)
if len(daily) < 2:
    st.info(
        f"Only {len(daily)} snapshot day so far — trends appear once the pipeline "
        "has run on several days."
    )
else:
    st.caption(
        f"{len(daily)} full sweeps. Each point is how many data roles were visible on "
        f"the boards that day — flat by design, since each Adzuna market is read up to "
        f"{SWEEP_CAP} postings a day. {LEFT_OUT} days are left out: the pipeline's "
        "ramp-up and its partial sweeps, whose low counts were the scraper, not the market."
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
    market_trend = full_sweeps_only(market_trend)
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
