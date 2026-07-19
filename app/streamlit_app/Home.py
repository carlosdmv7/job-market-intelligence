"""Job Market Intelligence — cross-market overview.

The front page compares the local markets side by side (NL/SE/DE/ES + the
remote-first boards); country-specific depth lives in its own page (NL visa
audit). Every number here comes straight from the marts.
"""

from __future__ import annotations

import altair as alt
import streamlit as st

from streamlit_app import ui
from streamlit_app.db import require_marts, run_df

st.set_page_config(page_title="Job Market Intelligence", page_icon="🧭", layout="wide")

st.title("🧭 Job Market Intelligence")
st.caption(
    "EU data & tech jobs across markets — ingested daily, enriched with an LLM, "
    "and backed by **auditable** visa-sponsorship signals."
)

require_marts(
    "marts.FT_JOB_POSTING",
    missing=(
        "Connected to the warehouse, but it has no marts yet. Run the pipeline:\n\n"
        "1. `make warehouse-init`\n2. `make ingest-all` / `make ingest-nl`\n"
        "3. `make enrich`\n4. `make dbt-build`"
    ),
)

totals = run_df(
    """
    select
        count(*)                                                  as postings,
        count(distinct country_code)                              as markets,
        count(distinct company_name)                              as companies,
        count(*) filter (where is_enriched)                       as enriched,
        count(*) filter (where is_recognised_sponsor and country_code = 'NL') as nl_sponsor_jobs
    from marts.FT_JOB_POSTING
    """
).iloc[0]

c1, c2, c3, c4 = st.columns(4)
c1.metric("Postings", f"{int(totals.postings):,}")
c2.metric("Local markets", f"{int(totals.markets)}", help="Countries with a local corpus.")
c3.metric("Companies", f"{int(totals.companies):,}")
c4.metric(
    "LLM-enriched",
    f"{int(totals.enriched):,}",
    help="Coverage accumulates daily within the free LLM quota (NL first).",
)

st.divider()

# --- markets side by side ---------------------------------------------------
st.markdown("#### Markets at a glance")
markets = run_df(
    """
    select
        country_code,
        count(*)                                            as postings,
        count(distinct company_name)                        as companies,
        count(*) filter (where is_recognised_sponsor)       as sponsor_jobs,
        count(*) filter (where is_enriched)                 as enriched,
        max(last_seen_at)                                   as last_seen
    from marts.FT_JOB_POSTING
    group by 1 order by postings desc
    """
)
markets["market"] = markets["country_code"].map(ui.market_label)

left, right = st.columns([2, 3], gap="large")
with left:
    ui.show(ui.hbar(markets, "market", "postings", value_title="postings"))
with right:
    ui.table(
        markets[["market", "postings", "companies", "sponsor_jobs", "enriched"]],
        column_config={
            "market": st.column_config.TextColumn("Market"),
            "postings": st.column_config.NumberColumn("Postings"),
            "companies": st.column_config.NumberColumn("Companies"),
            "sponsor_jobs": st.column_config.NumberColumn(
                "IND sponsor jobs", help="NL-specific: company is on the IND register."
            ),
            "enriched": st.column_config.NumberColumn("LLM-enriched"),
        },
    )

# --- top companies per market ----------------------------------------------
st.markdown("#### Who is hiring, per market")
tabs = st.tabs([ui.market_label(c) for c in markets["country_code"]])
for tab, code in zip(tabs, markets["country_code"], strict=True):
    with tab:
        where = "country_code is null" if code != code or code is None else "country_code = ?"
        params = () if where.startswith("country_code is null") else (code,)
        top = run_df(
            f"""
            select company_name as company, count(*) as openings,
                   max(cast(is_recognised_sponsor as int)) = 1 as ind_sponsor
            from marts.FT_JOB_POSTING
            where company_name is not null and {where}
            group by 1 order by openings desc limit 10
            """,
            params,
        )
        if top.empty:
            st.info("No postings for this market yet.")
            continue
        top["kind"] = top["ind_sponsor"].map({True: "IND sponsor (NL)", False: "Other"})
        chart = (
            alt.Chart(top)
            .mark_bar()
            .encode(
                y=alt.Y("company:N", sort="-x", title=None, axis=alt.Axis(labelLimit=240)),
                x=alt.X("openings:Q", title="open roles", axis=alt.Axis(grid=True, tickCount=4)),
                color=alt.Color(
                    "kind:N",
                    scale=alt.Scale(domain=["IND sponsor (NL)", "Other"], range=[ui.GOOD, ui.BLUE]),
                    title=None,
                ),
                tooltip=["company:N", "openings:Q", alt.Tooltip("kind:N", title="type")],
            )
            .properties(height=max(160, len(top) * 30 + 12))
        )
        ui.show(chart)

st.info(
    "**🔎 Job Explorer** — filter everything and open any posting's full card · "
    "**📈 Market Trends** — how the markets move over time · "
    "**🛂 NL Visa Audit** — the IND recognised-sponsor cross-reference · "
    "**💬 Ask the Data** — questions in natural language · "
    "**⚙️ How It Works** — pipeline, LLM prompt, and guardrails · "
    "**🎯 CV Match** — rank every posting against your CV (session-only)."
)
