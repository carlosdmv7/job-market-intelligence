"""NL Visa Audit — the deterministic IND recognised-sponsor cross-reference.

This is the specialized Netherlands page: every company is checked against the
official IND register of employers legally authorised to sponsor a
highly-skilled-migrant visa. A match is auditable — it carries a KvK number you
can verify on the public Chamber of Commerce register. The LLM never touches
this signal.

Every flag on this page opens to its evidence: the matched company name, its
KvK number (linked to the public registry), and — clearly marked as the
*secondary* signal — what the LLM read in the posting text, with its confidence
and the verbatim snippet it quoted.
"""

from __future__ import annotations

import pandas as pd
import streamlit as st
from streamlit_app import ui
from streamlit_app.db import require_marts, run_df

ui.configure_page("NL Visa Audit")
ui.page_header(
    title="🛂 NL Visa Audit",
    subtitle=(
        "Jobs at companies that can **legally sponsor** a relocation to the Netherlands — "
        "cross-referenced against the official IND register, each match verifiable by KvK "
        "number. Deterministic: no LLM involved."
    ),
)

with st.expander("What are IND and KvK? (plain-language)"):
    st.markdown(
        """
- **IND** is the Dutch immigration service. It publishes the official list of employers
  that are allowed to sponsor a work visa for non-EU hires.
- **KvK** is the Dutch chamber-of-commerce registry number — the equivalent of a Spanish
  CIF/NIF. Showing it proves the match is the *actual registered company*, not just a
  name that looks similar. Click any KvK link below to see the company on the public registry.
- **If you're an EU citizen you don't need any of this** — you have the right to work in
  NL already. This page exists for non-EU users and as the app's auditable-data showcase.
"""
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
        salary_raw, source, source_url, visa_evidence, visa_reasoning,
        is_enriched, posted_at, last_seen_at,
        {ui.SPONSORSHIP_SQL} as sponsorship
    from marts.FT_JOB_POSTING
    where {" and ".join(clauses)}
    order by {ui.POSTINGS_ORDER}
    """,
    tuple(params),
)

sponsor_rows = df[df["is_recognised_sponsor"]]
m1, m2, m3, m4 = st.columns(4)
m1.metric("Matching postings", f"{len(df):,}")
m2.metric("At recognised sponsors", f"{len(sponsor_rows):,}")
m3.metric("Distinct sponsor companies", f"{sponsor_rows['company_name'].nunique():,}")
m4.metric(
    "Not yet classified by the LLM",
    f"{int((~df['is_enriched'].fillna(False)).sum()):,}",
    help=(
        "These postings are awaiting enrichment within the free daily quota. "
        "Missing is **not** the same as negative — the register match above is "
        "unaffected either way."
    ),
)

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

# --- the grid: select a row to open its evidence ---------------------------
st.markdown("##### Postings")
st.caption(
    "Select a row to see exactly why it is flagged. Sorted: recognised sponsors first, then most recent."
)

grid = ui.add_salary_eur(df)
view = grid[
    [
        "title",
        "company_name",
        "sponsorship",
        "sponsor_kvk",
        "salary_eur",
        "posted_at",
        "source_url",
        "source",
    ]
]

event = st.dataframe(
    view,
    width="stretch",
    hide_index=True,
    on_select="rerun",
    selection_mode="single-row",
    height=420,
    column_config=ui.posting_columns(),
)

rows = event.selection.rows if event.selection else []
if not rows:
    st.info(
        "👆 Select a posting to open its evidence — the register match and the LLM's read, side by side."
    )
    ui.page_footer()
    st.stop()

row = df.iloc[rows[0]]
st.divider()
st.markdown(f"#### {row['title']} — {row['company_name']}")

ev1, ev2 = st.columns(2, gap="large")

with ev1:
    st.markdown("##### 🏛️ Deterministic signal — *primary*")
    if row["is_recognised_sponsor"]:
        st.success("**Recognised sponsor.** This employer is on the IND register.")
        st.markdown(f"Matched register entry: **{row['company_name']}**")
        kvk = row["sponsor_kvk"]
        if kvk and not pd.isna(kvk):
            st.markdown(
                f"KvK number **{kvk}** — "
                f"[verify on the public Chamber of Commerce registry ↗]"
                f"(https://www.kvk.nl/zoeken/?source=all&q={kvk})"
            )
        else:
            st.caption("The register lists this organisation without a KvK number.")
        st.caption(
            "Produced by a normalized-name join against the IND seed — the same "
            "normalization is applied to both sides. No model, no confidence score, "
            "nothing to hallucinate."
        )
    else:
        st.info("**No register match.** This company is not on the IND recognised-sponsor list.")
        st.caption(
            "That is a fact about the register, not about the company's intentions — "
            "and it is irrelevant if you already hold an EU passport."
        )

with ev2:
    st.markdown("##### 🧠 LLM read of the text — *secondary*")
    if not row["is_enriched"]:
        st.warning("**Not yet classified.** The classifier has not read this posting.")
        st.caption(
            "Enrichment is capped by the free Gemini quota (~50 postings/day) and "
            "accumulates daily, NL first. This is an absence of evidence, not evidence "
            "of absence — do not read it as 'no sponsorship'."
        )
    else:
        st.markdown(f"**{ui.visa_label(row['visa_status'], is_enriched=True)}**")
        if pd.notna(row["llm_confidence"]):
            st.progress(
                float(row["llm_confidence"]),
                text=f"model confidence {float(row['llm_confidence']):.0%}",
            )
        if row["visa_evidence"] and not pd.isna(row["visa_evidence"]):
            st.markdown("**Verbatim evidence quoted from the posting:**")
            st.markdown(f"> {row['visa_evidence']}")
        else:
            st.caption("The model quoted no supporting sentence — treat the read as weak.")
        if row["visa_reasoning"] and not pd.isna(row["visa_reasoning"]):
            st.caption(f"Model's rationale: {row['visa_reasoning']}")

st.link_button("Open the original posting ↗", row["source_url"])

ui.page_footer()
