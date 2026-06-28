"""The killer feature: visa-sponsoring roles for a relocating Spanish profile."""

from __future__ import annotations

import streamlit as st

from streamlit_app.db import run_df, table_exists

st.set_page_config(page_title="Visa Sponsorship", page_icon="🛂", layout="wide")
st.title("🛂 Visa Sponsorship")

if not table_exists("marts.FT_JOB_POSTING"):
    st.warning("Run the pipeline + `make dbt-build` first.")
    st.stop()

statuses = st.multiselect(
    "Visa status",
    ["explicit_yes", "likely_yes", "unclear", "likely_no", "explicit_no"],
    default=["explicit_yes", "likely_yes"],
)
min_conf = st.slider("Min visa confidence", 0.0, 1.0, 0.5, 0.05)
english_only = st.checkbox("English sufficient (no local language required)", value=True)

clauses = ["is_enriched"]
params: list = []
if statuses:
    placeholders = ", ".join("?" for _ in statuses)
    clauses.append(f"visa_status in ({placeholders})")
    params += statuses
clauses.append("coalesce(visa_confidence, 0) >= ?")
params.append(min_conf)
if english_only:
    clauses.append("(english_sufficient is true or requires_local_language is false)")

where = " and ".join(clauses)
df = run_df(
    f"""
    select title, company_name, country_code, source, visa_status,
           round(visa_confidence, 2) as confidence, english_sufficient,
           requires_local_language, relocation_support, salary_raw, source_url, visa_evidence
    from marts.FT_JOB_POSTING
    where {where}
    order by (visa_status = 'explicit_yes') desc, visa_confidence desc nulls last
    """,
    tuple(params),
)

st.caption(f"{len(df)} matching postings")
st.dataframe(
    df.drop(columns=["visa_evidence"]),
    use_container_width=True,
    hide_index=True,
    column_config={"source_url": st.column_config.LinkColumn("link")},
)

with st.expander("Why were these flagged? (model evidence)"):
    for _, row in df.head(25).iterrows():
        if row["visa_evidence"]:
            st.markdown(f"**{row['title']} — {row['company_name']}** ({row['visa_status']})")
            st.caption(f"> {row['visa_evidence']}")
