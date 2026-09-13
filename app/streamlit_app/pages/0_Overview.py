"""Overview — what is open right now, and in which stacks.

The first screen answers the question the app exists for: *are there live data
roles in my stack, and where?* Everything here is scoped to **active** postings
(still visible on their board) because a count that includes filled roles is
worse than no count — it reads as a number you can act on and it isn't.

Coverage is stated, not hidden: LLM extraction is quota-bound, so the share of
postings with a parsed stack is shown next to the stack chart rather than
letting the chart imply the whole corpus.
"""

from __future__ import annotations

import streamlit as st
from streamlit_app import ui
from streamlit_app.db import require_marts, run_df

ui.configure_page("EU data jobs")

ui.page_header(
    title="🧭 Job Market Intelligence",
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

TARGET = "is_target_role"
LIVE = "is_target_role and is_active"

totals = run_df(
    f"""
    select
        count(*) filter (where {LIVE})                                as live_roles,
        count(*) filter (where {TARGET})                              as all_roles,
        count(distinct company_name) filter (where {LIVE})             as companies,
        -- coalesce, not count(distinct country_code): postings with no country are
        -- remote/global and the table below lists them as their own market row, so
        -- counting only non-null codes made the metric disagree with the rows
        -- immediately beside it.
        count(distinct coalesce(country_code, 'REMOTE'))
            filter (where {LIVE})                                      as markets,
        count(*) filter (where {LIVE} and len(technologies) > 0)        as with_stack
    from marts.FT_JOB_POSTING
    """
).iloc[0]

live = int(totals.live_roles)
closed = int(totals.all_roles) - live

m1, m2, m3, m4 = st.columns(4)
m1.metric(
    "Open data roles",
    f"{live:,}",
    help="Still visible on their source board in the latest sweep.",
)
m2.metric("Companies hiring", f"{int(totals.companies):,}")
m3.metric(
    "Markets",
    f"{int(totals.markets)}",
    help="Tracked countries plus one bucket for remote roles with no country.",
)
m4.metric(
    "Closed, kept for history",
    f"{closed:,}",
    help=(
        "Postings we stopped seeing on their board — almost certainly filled. "
        "Excluded from browsing, retained so trends over time stay answerable."
    ),
)

st.divider()

# --- what stacks are actually being hired for ------------------------------
stack_col, market_col = st.columns([3, 2], gap="large")

with stack_col:
    st.markdown("#### Which stacks are hiring")
    stacks = run_df(
        f"""
        select tech, count(*) as roles from (
            select unnest(technologies) as tech
            from marts.FT_JOB_POSTING where {LIVE}
        ) group by 1 order by roles desc limit 15
        """
    )
    if stacks.empty:
        st.info("No technologies extracted yet — run `make enrich`.")
    else:
        ui.show(ui.hbar(stacks, "tech", "roles", color=ui.ACCENT, value_title="open roles"))
        with_stack = int(totals.with_stack)
        pct = with_stack / live if live else 0
        st.caption(
            f"Read from **{with_stack:,} of {live:,}** open roles ({pct:.0%}) — the LLM "
            "parses postings within a free daily quota, so this is a sample of the "
            "market, not a census of it."
        )

with market_col:
    st.markdown("#### Where they are")
    markets = run_df(
        f"""
        select country_code, count(*) as open_roles,
               count(distinct company_name) as companies
        from marts.FT_JOB_POSTING where {LIVE}
        group by 1 order by open_roles desc
        """
    )
    markets["market"] = markets["country_code"].map(ui.market_label)
    markets["share"] = markets["open_roles"] / max(live, 1)
    ui.table(
        markets[["market", "open_roles", "companies", "share"]],
        column_config={
            "market": st.column_config.TextColumn("Market"),
            "open_roles": st.column_config.NumberColumn("Roles"),
            "companies": st.column_config.NumberColumn("Firms"),
            "share": st.column_config.ProgressColumn(
                "Share", format="percent", min_value=0.0, max_value=1.0
            ),
        },
    )
    st.page_link("pages/2_Market_Trends.py", label="Compare markets in detail", icon="📈")

st.divider()

# --- where to go next -------------------------------------------------------
n1, n2 = st.columns(2, gap="large")
with n1:
    st.markdown("#### 🎯 Score them against your CV")
    st.markdown(
        "Paste or upload a CV and every open role gets a stack-overlap score — "
        "what you already have, what you're missing. Runs locally, no LLM call, "
        "and the CV never leaves the session."
    )
    st.page_link("pages/6_CV_Match.py", label="Open My Fit", icon="🎯")
with n2:
    st.markdown("#### 🔎 Browse and filter")
    st.markdown(
        "Filter by market, stack, seniority and whether English alone is enough "
        "to do the job. Open any posting to see the full card and its provenance."
    )
    st.page_link("pages/1_Job_Explorer.py", label="Open Find Jobs", icon="🔎")

ui.page_footer()
