"""Job Market Intelligence — overview."""

from __future__ import annotations

import streamlit as st

from streamlit_app.db import run_df, table_exists

st.set_page_config(page_title="Job Market Intelligence", page_icon="🧭", layout="wide")

st.title("🧭 Job Market Intelligence")
st.caption("Tech jobs across the EU, enriched for visa sponsorship & relocation fit.")

if not table_exists("marts.FT_JOB_POSTING"):
    st.warning(
        "No marts yet. Run the pipeline first:\n\n"
        "1. `make warehouse-init`\n2. `make ingest SOURCE=remotive`\n"
        "3. `make enrich`\n4. `make dbt-build`"
    )
    st.stop()

totals = run_df(
    """
    select
        count(*) as postings,
        count(*) filter (where is_visa_sponsor) as visa_sponsors,
        count(*) filter (where is_enriched) as enriched,
        count(distinct company_name) as companies
    from marts.FT_JOB_POSTING
    """
).iloc[0]

c1, c2, c3, c4 = st.columns(4)
c1.metric("Postings", f"{int(totals.postings):,}")
c2.metric("Visa sponsors", f"{int(totals.visa_sponsors):,}")
c3.metric("Enriched", f"{int(totals.enriched):,}")
c4.metric("Companies", f"{int(totals.companies):,}")

st.subheader("Postings by source")
st.bar_chart(run_df("select source, count(*) as postings from marts.FT_JOB_POSTING group by source order by postings desc").set_index("source"))

left, right = st.columns(2)
with left:
    st.subheader("Top roles")
    st.dataframe(
        run_df(
            "select coalesce(normalized_role, '(unclassified)') as role, count(*) as n "
            "from marts.FT_JOB_POSTING group by 1 order by n desc limit 15"
        ),
        use_container_width=True,
        hide_index=True,
    )
with right:
    st.subheader("Visa sponsorship breakdown")
    st.dataframe(
        run_df(
            "select coalesce(visa_status, '(not enriched)') as visa_status, count(*) as n "
            "from marts.FT_JOB_POSTING group by 1 order by n desc"
        ),
        use_container_width=True,
        hide_index=True,
    )

st.info("Pages → **Visa Sponsorship**, **Market Trends**, **Ask the Data** (text-to-SQL).")
