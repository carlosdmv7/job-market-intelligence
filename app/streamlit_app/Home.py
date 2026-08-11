"""Job Market Intelligence — the landing page.

The first screen states the *differentiator*, not the stack: every company is
checked against the official IND register, and the sponsor-rate gap between the
remote-first boards and the NL-local corpus is the measured proof that the
deterministic signal is doing real work. The tech story lives in How It Works.

Every number on this page is queried at page load. None is hardcoded — the
contrast headline included, which is why it is computed rather than quoted.
"""

from __future__ import annotations

import streamlit as st

from streamlit_app import ui
from streamlit_app.db import require_marts, run_df

ui.configure_page("Visa-sponsoring EU tech jobs")

ui.page_header(
    title="🧭 Job Market Intelligence",
    subtitle=(
        "EU data & tech jobs, ingested daily — with a visa-sponsorship signal you can "
        "**verify against a public register** instead of trusting a model."
    ),
)

require_marts(
    "marts.FT_JOB_POSTING",
    missing=(
        "Connected to the warehouse, but it has no marts yet. Run the pipeline:\n\n"
        "1. `make warehouse-init`\n2. `make ingest-all` / `make ingest-nl`\n"
        "3. `make enrich`\n4. `make dbt-build`"
    ),
)

# --- the differentiator, first screen ---------------------------------------
st.markdown(
    "#### Every company is matched against the official IND register of recognised "
    "sponsors — and every match carries a verifiable KvK number."
)

rates = run_df(
    """
    select
        case when country_code = 'NL' then 'nl' else 'remote' end   as corpus,
        count(distinct company_name)                                as companies,
        count(distinct company_name) filter (where is_recognised_sponsor) as sponsors
    from marts.FT_JOB_POSTING
    where company_name is not null
    group by 1
    """
).set_index("corpus")


def _rate(corpus: str) -> tuple[float, int, int]:
    if corpus not in rates.index:
        return 0.0, 0, 0
    row = rates.loc[corpus]
    companies, sponsors = int(row.companies), int(row.sponsors)
    return (sponsors / companies if companies else 0.0), sponsors, companies


nl_rate, nl_sponsors, nl_companies = _rate("nl")
remote_rate, remote_sponsors, remote_companies = _rate("remote")

d1, d2, d3 = st.columns([2, 2, 3], gap="large")
# Short labels on purpose: the heading above already says these are recognised-
# sponsor rates, and a truncated metric label reads as a bug.
d1.metric(
    "NL local corpus",
    f"{nl_rate:.0%}",
    help=f"{nl_sponsors:,} of {nl_companies:,} companies are on the IND register.",
)
d2.metric(
    "Remote-first boards",
    f"{remote_rate:.0%}",
    help=f"{remote_sponsors:,} of {remote_companies:,} companies are on the IND register.",
)
with d3:
    st.markdown(
        "**That gap is the product.** Remote-first boards barely overlap with the "
        "register; the Dutch local corpus does. A deterministic register match finds "
        "sponsors an LLM reading job text never could — and it works on postings the "
        "LLM has never seen."
    )
    st.page_link("pages/3_NL_Visa_Audit.py", label="See the audit, company by company →", icon="🛂")

st.divider()

# --- scale of the corpus ----------------------------------------------------
totals = run_df(
    """
    select
        count(*)                                                  as postings,
        count(distinct country_code)                              as markets,
        count(distinct company_name)                              as companies,
        count(*) filter (where is_enriched)                       as enriched,
        count(*) filter (where is_recognised_sponsor)             as sponsor_jobs
    from marts.FT_JOB_POSTING
    """
).iloc[0]

c1, c2, c3, c4 = st.columns(4)
c1.metric("Postings", f"{int(totals.postings):,}")
c2.metric("Local markets", f"{int(totals.markets)}", help="Countries with a local corpus.")
c3.metric("Companies", f"{int(totals.companies):,}")
c4.metric(
    "Jobs at recognised sponsors",
    f"{int(totals.sponsor_jobs):,}",
    help="Deterministic: the employer is on the IND register. No LLM involved.",
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
        count(*) filter (where not is_enriched)             as unclassified
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
        markets[["market", "postings", "companies", "sponsor_jobs", "enriched", "unclassified"]],
        column_config={
            "market": st.column_config.TextColumn("Market"),
            "postings": st.column_config.NumberColumn("Postings"),
            "companies": st.column_config.NumberColumn("Companies"),
            "sponsor_jobs": st.column_config.NumberColumn(
                "IND sponsor jobs", help="NL-specific: company is on the IND register."
            ),
            "enriched": st.column_config.NumberColumn("LLM-read"),
            "unclassified": st.column_config.NumberColumn(
                "Unclassified",
                help=(
                    "Not yet read by the LLM — awaiting the free daily quota. "
                    "Not a negative result."
                ),
            ),
        },
    )

# --- top companies per market ----------------------------------------------
st.markdown("#### Who is hiring, per market")
st.caption(
    "Colour is the visa signal: a register match, a text-only signal from the LLM, "
    "or a posting the LLM has not read yet."
)
tabs = st.tabs([ui.market_label(c) for c in markets["country_code"]])
for tab, code in zip(tabs, markets["country_code"], strict=True):
    with tab:
        is_null = code != code or code is None
        where = "country_code is null" if is_null else "country_code = ?"
        params = () if is_null else (code,)
        top = run_df(
            f"""
            with ranked as (
                select company_name, count(*) as openings
                from marts.FT_JOB_POSTING
                where company_name is not null and {where}
                group by 1 order by openings desc limit 10
            )
            select
                f.company_name as company,
                {ui.SPONSORSHIP_SQL} as sponsorship,
                count(*) as openings
            from marts.FT_JOB_POSTING f
            join ranked r on r.company_name = f.company_name
            where {where}
            group by 1, 2
            """,
            params + params,
        )
        if top.empty:
            st.info("No postings for this market yet.")
            continue
        ui.show(ui.sponsorship_bar(top, "company", "openings", value_title="open roles"))

st.info(
    "**🔎 Job Explorer** — filter everything and open any posting's full card · "
    "**📈 Market Trends** — how the markets move over time · "
    "**🛂 NL Visa Audit** — the IND recognised-sponsor cross-reference · "
    "**💬 Ask the Data** — questions in natural language · "
    "**⚙️ How It Works** — pipeline, LLM prompt, evals, and guardrails · "
    "**🎯 CV Match** — rank every posting against your CV (session-only)."
)

ui.page_footer()
