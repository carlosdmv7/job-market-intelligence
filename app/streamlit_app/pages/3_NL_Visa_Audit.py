"""NL Visa Audit — the deterministic IND recognised-sponsor cross-reference.

This is the specialized Netherlands page: every company is checked against the
official IND register of employers legally authorised to sponsor a
highly-skilled-migrant visa. A match is auditable — it carries a KvK number you
can verify on the public Chamber of Commerce register. The LLM never touches
this signal.
"""

from __future__ import annotations

import streamlit as st
from streamlit_app import ui
from streamlit_app.db import require_marts, run_df

st.set_page_config(page_title="NL Visa Audit", page_icon="🛂", layout="wide")
st.title("🛂 NL Visa Audit")
st.caption(
    "Jobs at companies that can **legally sponsor** a relocation to the Netherlands — "
    "cross-referenced against the official IND register (≈12.8k recognised sponsors), "
    "each match verifiable by KvK number. Deterministic: no LLM involved."
)

require_marts(
    "marts.FT_JOB_POSTING",
    missing="Connected, but no marts yet — run the pipeline, then `make dbt-build`.",
)

# --- why this signal matters: sponsor rate, local vs remote corpora --------
rates = run_df(
    """
    select
        case when country_code = 'NL' then 'NL local corpus (Adzuna)'
             else 'Other / remote boards' end             as corpus,
        count(distinct company_name)                       as companies,
        count(distinct company_name)
            filter (where is_recognised_sponsor)           as sponsors
    from marts.FT_JOB_POSTING
    where company_name is not null
    group by 1
    """
)
rates["sponsor_rate"] = (rates["sponsors"] / rates["companies"]).fillna(0)

r1, r2 = st.columns(2)
rate_rows = list(rates.sort_values("corpus", ascending=False).iterrows())[:2]
for col, (_, r) in zip((r1, r2), rate_rows, strict=False):
    col.metric(
        f"Sponsor rate — {r['corpus']}",
        f"{r['sponsor_rate']:.0%}",
        help=f"{int(r['sponsors'])} of {int(r['companies'])} companies are on the IND register.",
    )
st.caption(
    "The gap is the point: remote-first boards barely overlap with the register, the "
    "NL local corpus does. The deterministic check finds sponsors the LLM never could."
)

st.divider()

# --- filters ---------------------------------------------------------------
f1, f2, f3 = st.columns([3, 2, 2], gap="medium")
search = f1.text_input("Title contains", placeholder="engineer, analyst, ...")
sponsor_only = f2.toggle("Recognised sponsors only", value=True)
include_remote = f3.toggle(
    "Include remote jobs at IND sponsors",
    value=False,
    help="A recognised sponsor hiring remotely is still a legal sponsorship route.",
)

clauses = ["(country_code = 'NL'" + (" or is_recognised_sponsor)" if include_remote else ")")]
params: list = []
if sponsor_only:
    clauses.append("is_recognised_sponsor")
if search:
    clauses.append("lower(title) like ?")
    params.append(f"%{search.lower()}%")

df = run_df(
    f"""
    select
        company_name, title, country_code,
        is_recognised_sponsor, sponsor_kvk,
        visa_status, round(visa_confidence, 2) as llm_confidence,
        english_sufficient, requires_local_language, relocation_support,
        salary_raw, source, source_url, visa_evidence, is_enriched
    from marts.FT_JOB_POSTING
    where {" and ".join(clauses)}
    order by is_recognised_sponsor desc,
             (visa_status = 'explicit_yes') desc,
             company_name
    """,
    tuple(params),
)

sponsor_rows = df[df["is_recognised_sponsor"]]
m1, m2, m3 = st.columns(3)
m1.metric("Matching postings", f"{len(df):,}")
m2.metric("At recognised sponsors", f"{len(sponsor_rows):,}")
m3.metric("Distinct sponsor companies", f"{sponsor_rows['company_name'].nunique():,}")

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

# --- audit trail -----------------------------------------------------------
with st.expander("Audit trail: why is each company flagged?"):
    st.markdown(
        "Every ✅ below is a normalized-name match against the IND register; the KvK "
        "number links to the public Chamber of Commerce search so you can verify it "
        "yourself. The LLM line (when present) is the *secondary* text-based signal."
    )
    for _, row in df.head(25).iterrows():
        lines = [f"**{row['title']} — {row['company_name']}**"]
        if row["is_recognised_sponsor"]:
            kvk = row["sponsor_kvk"]
            kvk_txt = (
                f" ([KvK {kvk}](https://www.kvk.nl/zoeken/?source=all&q={kvk}))" if kvk else ""
            )
            lines.append(f"✅ IND recognised sponsor{kvk_txt} — legally authorised to sponsor.")
        if row["visa_evidence"]:
            lines.append(f"🧠 LLM ({row['visa_status']}): _{row['visa_evidence']}_")
        if len(lines) > 1:
            st.markdown("  \n".join(lines))
