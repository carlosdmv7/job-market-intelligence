"""Job Market Intelligence — overview."""

from __future__ import annotations

import streamlit as st

from streamlit_app import ui
from streamlit_app.db import require_marts, run_df

st.set_page_config(page_title="Job Market Intelligence", page_icon="🧭", layout="wide")

st.title("🧭 Job Market Intelligence")
st.caption(
    "EU tech jobs, enriched for **visa sponsorship & relocation fit** — with an "
    "auditable signal behind every flag."
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
        count(*)                                                            as postings,
        count(*) filter (where country_code = 'NL')                         as nl_postings,
        count(*) filter (where country_code = 'NL' and is_recognised_sponsor) as nl_sponsor_jobs,
        count(distinct company_name) filter (where is_recognised_sponsor)   as sponsor_companies
    from marts.FT_JOB_POSTING
    """
).iloc[0]

c1, c2, c3, c4 = st.columns(4)
c1.metric("Postings", f"{int(totals.postings):,}")
c2.metric("NL postings", f"{int(totals.nl_postings):,}")
c3.metric(
    "NL jobs at visa sponsors",
    f"{int(totals.nl_sponsor_jobs):,}",
    help="Company is on the IND register of employers authorised to sponsor a NL work visa.",
)
c4.metric("Recognised sponsor companies", f"{int(totals.sponsor_companies):,}")

st.divider()

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

st.markdown("##### 🛂 Recognised visa sponsors hiring in the Netherlands")
st.caption("Companies on the IND register with the most open roles — your best relocation leads.")
top_sponsors = run_df(
    """
    select company_name as company, count(*) as openings
    from marts.FT_JOB_POSTING
    where country_code = 'NL' and is_recognised_sponsor
    group by 1 order by openings desc limit 12
    """
)
if top_sponsors.empty:
    st.info("No recognised-sponsor postings yet — run `make ingest-nl` then `make dbt-build`.")
else:
    ui.show(ui.hbar(top_sponsors, "company", "openings", color=ui.GOOD, value_title="open roles"))

st.info(
    "Explore → **🛂 Visa Sponsorship**, **📈 Market Trends**, **💬 Ask the Data** (text-to-SQL)."
)
