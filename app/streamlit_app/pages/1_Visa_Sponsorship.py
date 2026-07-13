"""The killer feature: roles at employers that can sponsor a relocation to NL.

Primary signal is the **IND recognised-sponsor** cross-reference — deterministic,
auditable (KvK number), and available for every posting regardless of LLM
enrichment. The LLM's read of the posting text (``visa_status`` + evidence) is
shown as a secondary, softer signal.
"""

from __future__ import annotations

import streamlit as st
from streamlit_app.db import run_df, table_exists

st.set_page_config(page_title="Visa Sponsorship", page_icon="🛂", layout="wide")
st.title("🛂 Visa Sponsorship")
st.caption(
    "Jobs at companies that can **legally sponsor** your relocation — each match "
    "is cross-referenced against the official IND register of recognised sponsors "
    "(≈12.8k Dutch employers). Deterministic and verifiable by KvK number; the "
    "LLM's read of the posting text is a secondary signal."
)

if not table_exists("marts.FT_JOB_POSTING"):
    st.warning("Run the pipeline + `make dbt-build` first.")
    st.stop()

# --- filters ---------------------------------------------------------------
countries = run_df(
    "select distinct country_code from marts.FT_JOB_POSTING "
    "where country_code is not null order by 1"
)["country_code"].tolist()
default_country = ["NL"] if "NL" in countries else countries

c1, c2, c3 = st.columns([2, 2, 3])
with c1:
    picked = st.multiselect("Country", countries, default=default_country)
with c2:
    sponsor_only = st.toggle("Recognised sponsors only", value=True)
with c3:
    search = st.text_input("Title contains", placeholder="engineer, analyst, ...")

clauses: list[str] = []
params: list = []
if picked:
    clauses.append(f"country_code in ({', '.join('?' for _ in picked)})")
    params += picked
if sponsor_only:
    clauses.append("is_recognised_sponsor")
if search:
    clauses.append("lower(title) like ?")
    params.append(f"%{search.lower()}%")
where = (" where " + " and ".join(clauses)) if clauses else ""

df = run_df(
    f"""
    select
        company_name, title, country_code,
        is_recognised_sponsor, sponsor_kvk,
        visa_status, round(visa_confidence, 2) as llm_confidence,
        english_sufficient, requires_local_language, relocation_support,
        salary_raw, source, source_url, visa_evidence, is_enriched
    from marts.FT_JOB_POSTING
    {where}
    order by is_recognised_sponsor desc,
             (visa_status = 'explicit_yes') desc,
             company_name
    """,
    tuple(params),
)

# --- headline metrics ------------------------------------------------------
m1, m2, m3 = st.columns(3)
m1.metric("Matching postings", len(df))
m2.metric("Recognised sponsors", int(df["is_recognised_sponsor"].sum()))
m3.metric("Distinct sponsor companies", df.loc[df["is_recognised_sponsor"], "company_name"].nunique())

# --- table -----------------------------------------------------------------
st.dataframe(
    df.drop(columns=["visa_evidence", "is_enriched"]),
    use_container_width=True,
    hide_index=True,
    column_config={
        "source_url": st.column_config.LinkColumn("link", display_text="open"),
        "is_recognised_sponsor": st.column_config.CheckboxColumn("IND sponsor"),
        "sponsor_kvk": st.column_config.TextColumn("KvK"),
        "visa_status": st.column_config.TextColumn("LLM visa read"),
    },
)

# --- evidence (auditability) ----------------------------------------------
with st.expander("Why is each flagged? (evidence)"):
    for _, row in df.head(25).iterrows():
        lines = [f"**{row['title']} — {row['company_name']}**"]
        if row["is_recognised_sponsor"]:
            kvk = f" (KvK {row['sponsor_kvk']})" if row["sponsor_kvk"] else ""
            lines.append(f"✅ IND recognised sponsor{kvk} — legally authorised to sponsor a NL permit.")
        if row["visa_evidence"]:
            lines.append(f"🧠 LLM ({row['visa_status']}): _{row['visa_evidence']}_")
        if len(lines) > 1:
            st.markdown("  \n".join(lines))
