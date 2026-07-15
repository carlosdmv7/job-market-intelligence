"""The killer feature: roles at employers that can sponsor a relocation to NL.

Primary signal is the **IND recognised-sponsor** cross-reference — deterministic,
auditable (KvK number), available for every posting regardless of LLM enrichment.
The LLM's read of the posting text (``visa_status`` + evidence) is secondary.
"""

from __future__ import annotations

import streamlit as st
from streamlit_app import ui
from streamlit_app.db import require_marts, run_df

st.set_page_config(page_title="Visa Sponsorship", page_icon="🛂", layout="wide")
st.title("🛂 Visa Sponsorship")
st.caption(
    "Jobs at companies that can **legally sponsor** your relocation — cross-referenced "
    "against the official IND register of recognised sponsors (≈12.8k Dutch employers), "
    "verifiable by KvK number. The LLM's read of the posting text is a secondary signal."
)

require_marts(
    "marts.FT_JOB_POSTING",
    missing="Connected, but no marts yet — run the pipeline, then `make dbt-build`.",
)

# --- filters ---------------------------------------------------------------
countries = run_df(
    "select distinct country_code from marts.FT_JOB_POSTING "
    "where country_code is not null order by 1"
)["country_code"].tolist()
default_country = ["NL"] if "NL" in countries else countries

f1, f2, f3 = st.columns([2, 2, 3], gap="medium")
picked = f1.multiselect("Country", countries, default=default_country)
sponsor_only = f2.toggle("Recognised sponsors only", value=True)
search = f3.text_input("Title contains", placeholder="engineer, analyst, ...")

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
sponsor_rows = df[df["is_recognised_sponsor"]]
m1, m2, m3 = st.columns(3)
m1.metric("Matching postings", f"{len(df):,}")
m2.metric("At recognised sponsors", f"{len(sponsor_rows):,}")
m3.metric("Distinct sponsor companies", f"{sponsor_rows['company_name'].nunique():,}")

# --- top sponsors chart ----------------------------------------------------
if not sponsor_rows.empty:
    st.markdown("##### Recognised sponsors with the most open roles")
    top = (
        sponsor_rows.groupby("company_name")
        .size()
        .reset_index(name="openings")
        .sort_values("openings", ascending=False)
        .head(12)
    )
    ui.show(ui.hbar(top, "company_name", "openings", color=ui.GOOD, value_title="open roles"))

# --- table -----------------------------------------------------------------
st.markdown("##### Postings")
ui.table(
    df.drop(columns=["visa_evidence", "is_enriched"]),
    column_config={
        "source_url": st.column_config.LinkColumn("link", display_text="open"),
        "is_recognised_sponsor": st.column_config.CheckboxColumn("IND sponsor"),
        "sponsor_kvk": st.column_config.TextColumn("KvK"),
        "visa_status": st.column_config.TextColumn("LLM visa read"),
        "llm_confidence": st.column_config.NumberColumn("LLM conf.", format="%.2f"),
    },
)

# --- evidence (auditability) ----------------------------------------------
with st.expander("Why is each flagged? (evidence)"):
    for _, row in df.head(25).iterrows():
        lines = [f"**{row['title']} — {row['company_name']}**"]
        if row["is_recognised_sponsor"]:
            kvk = f" (KvK {row['sponsor_kvk']})" if row["sponsor_kvk"] else ""
            lines.append(
                f"✅ IND recognised sponsor{kvk} — legally authorised to sponsor a NL permit."
            )
        if row["visa_evidence"]:
            lines.append(f"🧠 LLM ({row['visa_status']}): _{row['visa_evidence']}_")
        if len(lines) > 1:
            st.markdown("  \n".join(lines))
