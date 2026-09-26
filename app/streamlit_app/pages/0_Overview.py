"""Overview — what is open right now, what each market asks for, and how fast
it moves.

The first screen answers the question the app exists for: *are there live data
roles in my stack, and where?* Everything here is scoped to **active** postings
(still visible on their board) because a count that includes filled roles is
worse than no count — it reads as a number you can act on and it isn't.

The stack chart used to rank technologies by raw mentions across all markets.
That ranking was Sweden's: JobTech carries each posting's full text, where the
LLM finds ~7 technologies, and Adzuna returns a snippet, where it finds ~2 —
so 75 of the 94 "python" mentions were Swedish. The heatmap compares each
market's *mix* instead, which holds whatever the depth of the text behind it.
"""

from __future__ import annotations

import pandas as pd
import streamlit as st
from streamlit_app import ui
from streamlit_app.charts import bar_daily_new_roles, heatmap_stack_mix
from streamlit_app.db import require_marts, run_df
from streamlit_app.theme import show

ui.configure_page("EU data jobs")

ui.page_header(
    title="Job Market Intelligence",
    subtitle=(
        "Live data, analytics and ML roles across the EU — ingested daily, "
        "de-duplicated across boards, and ranked against **your** stack."
    ),
)

require_marts(
    "marts.FT_JOB_POSTING",
    missing=(
        "Connected to the warehouse, but it has no marts yet. Run the pipeline:\n\n"
        "1. `make warehouse-init`\n2. `make ingest-all`\n"
        "3. `make enrich`\n4. `make dbt-build`"
    ),
)

LIVE = "is_target_role and is_active"

totals = run_df(
    f"""
    select
        count(*) filter (where {LIVE})                                as live_roles,
        count(distinct company_name) filter (where {LIVE})             as companies,
        count(*) filter (where {LIVE} and english_sufficient)           as english_ok
    from marts.FT_JOB_POSTING
    """
).iloc[0]

live = int(totals.live_roles)

# --- the daily flow ---------------------------------------------------------
# A sweep that tracked far fewer postings than usual is the scraper's bad day,
# not the market's: flagged, drawn grey, and kept out of the average.
PARTIAL_SWEEP = 0.85
FLOW_DAYS = 60

daily = run_df(
    f"""
    select date_key as day,
           count(*) filter (where is_target_role)                  as tracked,
           count(*) filter (where is_target_role and is_first_seen) as new_roles
    from marts.FT_JOB_SNAPSHOT_DAILY
    where {ui.market_wide()}
    group by 1 order by 1
    """
)
if not daily.empty:
    daily["day"] = pd.to_datetime(daily["day"])
    daily["partial"] = daily["tracked"] < PARTIAL_SWEEP * daily["tracked"].median()
    full = daily[~daily["partial"]].set_index("day")["new_roles"]
    daily["avg7"] = daily["day"].map(full.rolling(7, min_periods=4).mean())
    # The first days of the history are the backfill, when every posting was
    # "first seen" at once — a spike that describes the pipeline starting.
    daily = daily.tail(FLOW_DAYS)

recent = daily[~daily["partial"]] if not daily.empty else daily
# (this week, the week before), over full sweeps only; None until two weeks exist.
weeks = (
    (int(recent.tail(7)["new_roles"].sum()), int(recent.tail(14).head(7)["new_roles"].sum()))
    if len(recent) >= 14
    else None
)

m1, m2, m3, m4 = st.columns(4)
m1.metric(
    "Open data roles",
    f"{live:,}",
    help="Still visible on their source board in the latest sweep.",
)
m2.metric(
    "New in the last 7 days",
    f"{weeks[0]:,}" if weeks else "—",
    delta=f"{weeks[0] - weeks[1]:+,} vs the week before" if weeks else None,
    # Neutral, no arrow: more new postings is not "good" and fewer is not
    # "bad" — it is the week, and a red arrow would editorialise.
    delta_color="off",
    delta_arrow="off",
    help="Data roles first seen on a board in the last seven full sweeps.",
)
m3.metric("Companies hiring", f"{int(totals.companies):,}")
m4.metric(
    "English is enough",
    f"{totals.english_ok / live:.0%}" if live else "—",
    help="Share of open roles where the posting says, or implies, that English "
    "alone is enough to do the job — read by the LLM from the posting text.",
)

# --- what each market asks for, and what just landed ------------------------
mix_col, new_col = st.columns([3, 2], gap="large")

with mix_col:
    st.markdown("#### What each market asks for")
    mix = run_df(
        f"""
        with mentions as (
            select country_code, unnest(technologies) as tech
            from marts.FT_JOB_POSTING
            where {LIVE} and country_code is not null and {ui.market_wide()}
        ),
        mix as (
            select country_code, tech, count(*) as mentions,
                   count(*) * 1.0 / sum(count(*)) over (partition by country_code) as share
            from mentions group by 1, 2
        ),
        top as (select tech from mix group by 1 order by sum(share) desc limit 12)
        select * from mix where tech in (select tech from top)
        """
    )
    if mix.empty:
        st.info("No technologies extracted yet — run `make enrich`.")
    else:
        # Columns in order of open roles, biggest market first.
        order = run_df(
            f"""
            select country_code, count(*) as n from marts.FT_JOB_POSTING
            where {LIVE} and country_code is not null and {ui.market_wide()}
            group by 1 order by n desc
            """
        )["country_code"].tolist()
        # Every market x technology cell, so a stack a market never names reads
        # as 0% rather than as a hole in the grid.
        grid = pd.MultiIndex.from_product(
            [order, sorted(mix["tech"].unique())], names=["country_code", "tech"]
        )
        mix = mix.set_index(["country_code", "tech"]).reindex(grid, fill_value=0).reset_index()
        mix["market"] = mix["country_code"].map(ui.market_label)
        show(heatmap_stack_mix(mix, [ui.market_label(c) for c in order]))
        st.caption(
            "Each column is one market's mix: of every technology its postings name, "
            "the share that is this one. Markets are read at different depths — "
            "Sweden's board gives full postings, the others a snippet — so the mix "
            "compares fairly where raw counts would not. Remote roles are too few to "
            "have a column, and Ireland — read from a list of employers, not its whole "
            "market — is left out of the comparison."
        )
    # Out of the comparison is not out of sight: Ireland gets its own line, and
    # the link opens Market Detail with it already picked.
    ireland = run_df(
        f"""
        select count(*) as roles, count(distinct company_name) as companies
        from marts.FT_JOB_POSTING where {LIVE} and country_code = 'IE'
        """
    ).iloc[0]
    if int(ireland.roles):
        st.page_link(
            "pages/3_Market_Detail.py",
            label=(
                f"{ui.market_label('IE')}: {int(ireland.roles)} open roles at "
                f"{int(ireland.companies)} tech employers, read from their own career sites"
            ),
            icon=":material/arrow_forward:",
            icon_position="right",
            query_params={"market": "IE"},
        )

with new_col:
    st.markdown("#### Just posted")
    newest = run_df(
        f"""
        select title, company_name, country_code, technologies,
               coalesce(apply_url, source_url) as url, posted_at
        from marts.FT_JOB_POSTING
        where {LIVE} and posted_at is not null
        order by posted_at desc
        limit 4
        """
    )
    for job in newest.itertuples():
        with st.container(border=True):
            st.markdown(
                f"**{job.title}**  \n{job.company_name} · {ui.market_label(job.country_code)}"
            )
            raw = job.technologies
            # A posting the LLM has not read has no list at all — None or pd.NA,
            # depending on the connection — not an empty one.
            techs = [] if raw is None or pd.api.types.is_scalar(raw) else list(raw)[:4]
            chips = " ".join(f":gray-badge[{t}]" for t in techs)
            posted = pd.Timestamp(job.posted_at)
            st.markdown(
                (chips + "  \n" if chips else "")
                + f":small[:gray[Posted {posted:%-d %b}] · [open ↗]({job.url})]"
            )
    st.page_link(
        "pages/1_Job_Explorer.py", label="Browse every open role", icon=":material/arrow_forward:"
    )

# --- the flow ---------------------------------------------------------------
if not daily.empty:
    st.markdown("#### New data roles, day by day")
    show(bar_daily_new_roles(daily))
    st.caption(
        "Roles first seen on a board each day, with the 7-day average. Grey days are "
        "partial sweeps — the pipeline tracked far fewer postings than usual — so "
        "they are left out of the average. Ireland, read from a list of employers "
        "rather than its boards, is not counted here."
    )

st.divider()

# --- where to go next -------------------------------------------------------
n1, n2, n3 = st.columns(3, gap="large")
for col, page, icon, label, line in [
    (
        n1,
        "pages/6_CV_Match.py",
        "target",
        "My Fit",
        "Upload a CV and every open role gets a stack-overlap score. Runs locally.",
    ),
    (
        n2,
        "pages/1_Job_Explorer.py",
        "search",
        "Find Jobs",
        "Filter by market, stack, seniority and whether English alone is enough.",
    ),
    (
        n3,
        "pages/2_Market_Trends.py",
        "trending_up",
        "Market Trends",
        "Every market side by side, and how its stacks move over time.",
    ),
]:
    with col, st.container(border=True):
        st.page_link(page, label=f"**{label}**", icon=f":material/{icon}:")
        st.caption(line)

ui.page_footer()
