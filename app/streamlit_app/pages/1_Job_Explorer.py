"""Job Explorer — filter every market, open any posting's full card.

The card (ficha) is where the two visa signals become inspectable: the
deterministic IND match (with its KvK number) and the LLM's read of the text
(status, verbatim evidence, one-sentence reasoning, and which model/prompt
produced it). Descriptions live in staging, so the card fetches them by
content_hash on demand.
"""

from __future__ import annotations

import pandas as pd
import streamlit as st
from streamlit_app import ui
from streamlit_app.db import require_marts, run_df

from jmi_core.text import strip_html

st.set_page_config(page_title="Job Explorer", page_icon="🔎", layout="wide")
st.title("🔎 Job Explorer")
st.caption("All markets, all sources. Select a row to open the full posting card.")

require_marts(
    "marts.FT_JOB_POSTING",
    missing="Connected, but no marts yet — run the pipeline, then `make dbt-build`.",
)

# --- filters ---------------------------------------------------------------
codes = run_df("select distinct country_code from marts.FT_JOB_POSTING order by 1 nulls last")[
    "country_code"
].tolist()
market_options = [ui.market_label(c) for c in codes]
label_to_code = dict(zip(market_options, codes, strict=True))

techs = run_df(
    """
    select tech, count(*) as n from (
        select unnest(technologies) as tech from marts.FT_JOB_POSTING
    ) group by 1 order by n desc limit 40
    """
)["tech"].tolist()

f1, f2, f3, f4 = st.columns([2, 2, 2, 1], gap="medium")
picked_markets = f1.multiselect("Market", market_options, default=[])
search = f2.text_input("Title or company contains", placeholder="engineer, dbt, Spotify…")
picked_techs = f3.multiselect("Technologies (LLM-extracted)", techs)
sort = f4.selectbox("Sort by", ["Newest", "Language fit", "Visa signal"])

ORDERINGS = {
    "Newest": "last_seen_at desc",
    "Language fit": "(english_sufficient is true) desc, is_enriched desc, last_seen_at desc",
    "Visa signal": (
        "is_recognised_sponsor desc, "
        "(visa_status in ('explicit_yes', 'likely_yes')) desc, last_seen_at desc"
    ),
}

g1, g2, g3, g4 = st.columns(4, gap="medium")
sponsor_only = g1.toggle("IND sponsor only", help="Company on the Dutch IND register.")
english_only = g2.toggle("English is sufficient", help="Per the LLM read of the text.")
visa_signal = g3.toggle("Visa signal in text", help="LLM read: explicit_yes or likely_yes.")
enriched_only = g4.toggle("LLM-enriched only")

clauses: list[str] = []
params: list = []
if picked_markets:
    picked_codes = [label_to_code[m] for m in picked_markets]
    non_null = [c for c in picked_codes if not pd.isna(c)]
    parts = []
    if non_null:
        parts.append(f"country_code in ({', '.join('?' for _ in non_null)})")
        params += non_null
    if len(non_null) != len(picked_codes):
        parts.append("country_code is null")
    clauses.append("(" + " or ".join(parts) + ")")
if search:
    clauses.append("(lower(title) like ? or lower(company_name) like ?)")
    params += [f"%{search.lower()}%"] * 2
for tech in picked_techs:
    clauses.append("list_contains(technologies, ?)")
    params.append(tech)
if sponsor_only:
    clauses.append("is_recognised_sponsor")
if english_only:
    clauses.append("english_sufficient")
if visa_signal:
    clauses.append("visa_status in ('explicit_yes', 'likely_yes')")
if enriched_only:
    clauses.append("is_enriched")
where = (" where " + " and ".join(clauses)) if clauses else ""

df = run_df(
    f"""
    select
        job_posting_key, content_hash, title, company_name, country_code, location_raw,
        seniority, salary_raw, source, source_url, apply_url, posted_at, last_seen_at,
        is_recognised_sponsor, sponsor_kvk, visa_status, visa_confidence, visa_evidence,
        visa_reasoning, is_enriched, english_sufficient, requires_local_language,
        working_languages, relocation_support, technologies, normalized_role,
        enrichment_model, enrichment_prompt_version, enriched_at, enrichment_confidence,
        remote_policy, employment_type
    from marts.FT_JOB_POSTING
    {where}
    order by {ORDERINGS[sort]}
    limit 1000
    """,
    tuple(params),
)

st.caption(f"**{len(df):,}** matching postings (showing up to 1,000).")

view = df[
    [
        "title",
        "company_name",
        "seniority",
        "english_sufficient",
        "is_recognised_sponsor",
        "visa_status",
        "salary_raw",
        "source",
    ]
].copy()
view.insert(2, "market", df["country_code"].map(ui.market_label))

event = st.dataframe(
    view,
    width="stretch",
    hide_index=True,
    on_select="rerun",
    selection_mode="single-row",
    height=420,
    column_config={
        "title": st.column_config.TextColumn("Title", width="large"),
        "company_name": st.column_config.TextColumn("Company"),
        "market": st.column_config.TextColumn("Market"),
        "seniority": st.column_config.TextColumn("Seniority"),
        "english_sufficient": st.column_config.CheckboxColumn(
            "EN ok", help="English alone is enough, per the LLM read. Empty = not enriched yet."
        ),
        "is_recognised_sponsor": st.column_config.CheckboxColumn(
            "Visa", help="Company can legally sponsor a NL work visa (IND list)."
        ),
        "visa_status": st.column_config.TextColumn("LLM visa read"),
        "salary_raw": st.column_config.TextColumn("Salary (raw)"),
        "source": st.column_config.TextColumn("Source"),
    },
)


# --- ficha de oferta -------------------------------------------------------
def _txt(value) -> str | None:
    """A scalar cell as text, treating None/NaN/pd.NA uniformly as absent."""
    if value is None or (pd.api.types.is_scalar(value) and pd.isna(value)):
        return None
    return str(value)


def _items(value) -> list:
    """An array cell as a list; DuckDB returns pd.NA (not None) when NULL."""
    if value is None or (pd.api.types.is_scalar(value) and pd.isna(value)):
        return []
    return list(value)


rows = event.selection.rows if event.selection else []
if not rows:
    st.info("👆 Select a row to open the posting card.")
    st.stop()

row = df.iloc[rows[0]]
st.divider()

head, links = st.columns([4, 1], gap="large")
with head:
    st.subheader(row["title"])
    location = _txt(row["location_raw"])
    st.markdown(
        f"**{_txt(row['company_name']) or 'Unknown company'}** · "
        f"{ui.market_label(row['country_code'])}" + (f" · {location}" if location else "")
    )
    meta = [
        f"source: `{row['source']}`",
        f"first posted: {row['posted_at'].date()}" if pd.notna(row["posted_at"]) else None,
        f"last seen: {row['last_seen_at'].date()}" if pd.notna(row["last_seen_at"]) else None,
        f"salary: {_txt(row['salary_raw'])}" if _txt(row["salary_raw"]) else None,
        f"type: {_txt(row['employment_type'])}" if _txt(row["employment_type"]) else None,
        f"remote: {_txt(row['remote_policy'])}" if _txt(row["remote_policy"]) else None,
    ]
    st.caption(" · ".join(m for m in meta if m))
with links:
    st.link_button("Open posting ↗", row["source_url"], width="stretch")
    apply_url = _txt(row["apply_url"])
    if apply_url and apply_url != row["source_url"]:
        st.link_button("Apply ↗", apply_url, width="stretch")

sig1, sig2 = st.columns(2, gap="large")
with sig1:
    st.markdown("##### 🗣️ Can you work there in English?")
    if not row["is_enriched"]:
        st.markdown("_Not yet enriched._ Coverage accumulates daily within the free LLM quota.")
    else:
        if pd.isna(row["english_sufficient"]):
            st.markdown("The text doesn't say which language the job needs.")
        elif row["english_sufficient"]:
            st.success("**English is enough** for this job, per the posting text.")
        else:
            st.warning("**The local language is required** to do this job (not just a plus).")
        langs = _items(row["working_languages"])
        if langs:
            st.markdown("Working languages: " + ", ".join(f"`{lang}`" for lang in langs))
        if pd.notna(row["relocation_support"]) and row["relocation_support"]:
            st.markdown("📦 The posting mentions relocation support.")

    st.markdown("##### 🏛️ Visa sponsorship (for non-EU candidates)")
    if row["is_recognised_sponsor"]:
        kvk = _txt(row["sponsor_kvk"])
        st.success(
            "**Recognised sponsor** — this company is on the Dutch government's (IND) "
            "official list of employers allowed to sponsor a work visa."
        )
        if kvk:
            st.markdown(
                f"Company registry nº (KvK, the Dutch CIF) **{kvk}** — "
                f"[check it on the public registry](https://www.kvk.nl/zoeken/?source=all&q={kvk})"
            )
    else:
        st.caption(
            "Not on the Dutch sponsor list. EU citizens don't need this — it only matters "
            "if you'd need a work visa."
        )
with sig2:
    st.markdown("##### 🧠 What the LLM read in the text")
    if not row["is_enriched"]:
        st.markdown("_Not yet enriched._")
    else:
        st.markdown(f"**{ui.VISA_LABELS.get(row['visa_status'], row['visa_status'])}**")
        if pd.notna(row["visa_confidence"]):
            st.progress(
                float(row["visa_confidence"]),
                text=f"visa confidence {row['visa_confidence']:.0%}",
            )
        if _txt(row["visa_reasoning"]):
            st.markdown(f"**Why:** {_txt(row['visa_reasoning'])}")
        if _txt(row["visa_evidence"]):
            st.markdown(f"**Verbatim evidence:** “{_txt(row['visa_evidence'])}”")
        provenance = (
            f"model `{row['enrichment_model']}` · prompt `{row['enrichment_prompt_version']}` · "
            f"enriched {row['enriched_at'].date() if pd.notna(row['enriched_at']) else '—'}"
        )
        if pd.notna(row["enrichment_confidence"]):
            provenance += f" · overall confidence {row['enrichment_confidence']:.0%}"
        st.caption(provenance)

techs_list = _items(row["technologies"])
if techs_list:
    st.markdown("**Technologies:** " + " ".join(f"`{t}`" for t in techs_list))

with st.expander("Full description (as scraped)"):
    desc = run_df(
        "select description_raw from staging.stg_job_postings where content_hash = ? limit 1",
        (row["content_hash"],),
    )
    text = strip_html(desc.iloc[0, 0]) if not desc.empty else None
    if text:
        st.text(text)
    else:
        st.markdown("_No description captured for this posting._")
