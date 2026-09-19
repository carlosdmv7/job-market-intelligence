"""Find Jobs — filter every market, open any posting's full card.

The card leads with what decides whether to apply: the stack the role asks for,
the seniority, and whether English alone is enough. The two visa signals — the
deterministic IND register match with its KvK number, and the model's read of
the text with its verbatim evidence — are inspectable underneath, where they
are evidence of how the project treats signals rather than the headline.

Descriptions live in staging, so the card fetches them by content_hash on
demand rather than carrying every posting's full text through the grid query.
"""

from __future__ import annotations

import pandas as pd
import streamlit as st
from streamlit_app import ui
from streamlit_app.db import require_marts, run_df

from jmi_core.text import strip_html

ui.configure_page("Find Jobs")
ui.page_header(
    title="🔎 Find Jobs",
    subtitle=(
        "Open data roles across every market and source, de-duplicated. "
        "Select a row to open the full posting card."
    ),
)

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

ORDERINGS = {
    # Default: freshest sighting first. Most recently confirmed open is the most
    # actionable ordering once you are browsing only live postings.
    "Last seen": "last_seen_at desc nulls last",
    "Newest posted": "posted_at desc nulls last",
    "Language fit": "(detected_language = 'en') desc, last_seen_at desc",
    "Stack read": "len(technologies) desc, last_seen_at desc",
}

f1, f2, f3, f4 = st.columns([2, 2, 2, 1], gap="medium")
picked_markets = f1.multiselect("Market", market_options, default=[])
search = f2.text_input("Title or company contains", placeholder="engineer, dbt, Spotify…")
picked_techs = f3.multiselect("Technologies (LLM-extracted)", techs)
sort = f4.selectbox("Sort by", list(ORDERINGS))


g1, g2, g3, g4 = st.columns(4, gap="medium")
active_only = g1.toggle(
    "Open only",
    value=True,
    help=(
        "Still visible on its source board in the latest sweep. Boards delete "
        "filled roles instead of closing them, so a posting we stopped seeing "
        "is almost certainly gone. Off shows the full history."
    ),
)
data_roles_only = g2.toggle(
    "Data roles only",
    value=True,
    help=(
        "Data / analytics / ML titles. The free boards publish their whole "
        "catalogue, so off also shows sales, finance and hospitality."
    ),
)
english_only = g3.toggle(
    "Written in English",
    help=(
        "The language the ad itself is written in — detected on ingest, so it "
        "covers every posting rather than only the ones the LLM has read. Of the "
        "English-language postings it has read, it calls English sufficient 87% "
        "of the time; of the Dutch-language ones, never."
    ),
)
# "IND sponsor only" and a "Visa signal" ordering used to sit here — two of the
# nine controls on the page used daily, both answering a question an EU passport
# already answers. The register cross-reference is still in the app, as a
# section of the Netherlands market page, where it is a property of that market
# rather than a filter on every search.
enriched_only = g4.toggle(
    "Stack read only",
    help=(
        "Has at least one technology extracted. Truncated sources (Adzuna, "
        "~500 characters per ad) often name none — see Market Detail."
    ),
)

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
if active_only:
    clauses.append("is_active")
if data_roles_only:
    clauses.append("is_target_role")
if english_only:
    clauses.append("detected_language = 'en'")
if enriched_only:
    clauses.append("len(technologies) > 0")
where = (" where " + " and ".join(clauses)) if clauses else ""

df = run_df(
    f"""
    select
        content_hash, title, company_name, country_code, location_raw,
        seniority, salary_raw, source, source_url, apply_url, posted_at, last_seen_at,
        detected_language, technologies, normalized_role,
        is_enriched, english_sufficient, working_languages, relocation_support,
        is_recognised_sponsor, sponsor_kvk, visa_status, visa_confidence, visa_evidence,
        visa_reasoning,
        enrichment_model, enrichment_prompt_version, enriched_at, enrichment_confidence,
        remote_policy, employment_type
    from marts.FT_JOB_POSTING
    {where}
    order by {ORDERINGS[sort]}
    limit 1000
    """,
    tuple(params),
)

st.caption(
    f"**{len(df):,}** matching "
    + ("open roles" if active_only else "postings")
    + " (showing up to 1,000)."
)

grid = ui.add_salary_eur(df)
grid["market"] = grid["country_code"].map(ui.market_label)
# The stack sits where the visa bucket used to. That column read "No
# sponsorship evidence" on nearly every row — a constant, taking the widest
# slot in a table whose job is to help you spot a role worth opening. The visa
# signal is still filterable, sortable, and shown in full on the card.
view = grid[
    [
        "title",
        "company_name",
        "market",
        "seniority",
        "technologies",
        "english_sufficient",
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
    column_config=ui.posting_columns(
        seniority=st.column_config.TextColumn("Seniority"),
        technologies=st.column_config.ListColumn(
            "Stack", help="Technologies the LLM found in the text. Empty = not read yet."
        ),
        english_sufficient=st.column_config.CheckboxColumn(
            "EN ok",
            help="English alone is enough, per the LLM read. Empty = not yet classified.",
        ),
    ),
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


rows = ui.selected_rows(event)
if not rows:
    st.info("👆 Select a row to open the posting card.")
    ui.page_footer()
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

# The card leads with fit, because that is what the app is for. Everything the
# LLM read about the *work* comes first; the visa cross-reference is real and
# auditable but answers a question an EU passport already answers, so it sits
# under a fold rather than beside the stack.
if not row["is_enriched"]:
    st.info(
        "**The LLM has not read this posting yet** — no stack, seniority or working "
        "language for it. Not read is not the same as nothing found: it is in the "
        "queue, which clears roughly 200 postings a day.",
        icon="⏳",
    )
else:
    fit1, fit2 = st.columns(2, gap="large")
    with fit1:
        st.markdown("##### 🧰 The stack this role asks for")
        techs_list = _items(row["technologies"])
        if techs_list:
            st.markdown(" ".join(f"`{t}`" for t in techs_list))
        else:
            st.caption("The LLM read this posting but found no named technologies in it.")
        bits = [
            f"**Role:** {_txt(row['normalized_role'])}" if _txt(row["normalized_role"]) else None,
            f"**Seniority:** {_txt(row['seniority'])}" if _txt(row["seniority"]) else None,
        ]
        if any(bits):
            st.markdown(" · ".join(b for b in bits if b))
        st.page_link("pages/6_CV_Match.py", label="Score this stack against your CV", icon="🎯")

    with fit2:
        st.markdown("##### 🗣️ Can you do this job in English?")
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
        st.caption(
            f"The ad itself is written in `{_txt(row['detected_language']) or 'unknown'}` — "
            "detected on ingest, independently of the model's read."
        )

    provenance = (
        f"model `{row['enrichment_model']}` · prompt `{row['enrichment_prompt_version']}` · "
        f"read {row['enriched_at'].date() if pd.notna(row['enriched_at']) else '—'}"
    )
    if pd.notna(row["enrichment_confidence"]):
        provenance += f" · overall confidence {row['enrichment_confidence']:.0%}"
    st.caption(provenance)

with st.expander("🛂 Visa sponsorship — only if you would need one"):
    st.caption(
        "Irrelevant with an EU passport. Kept because it is the one question this "
        "project can answer two ways, and the two are shown side by side."
    )
    v1, v2 = st.columns(2, gap="large")
    with v1:
        st.markdown("**🏛️ The register says** (deterministic)")
        if row["is_recognised_sponsor"]:
            kvk = _txt(row["sponsor_kvk"])
            st.success(
                "**Recognised sponsor** — on the Dutch government's (IND) official list "
                "of employers allowed to sponsor a work visa."
            )
            if kvk:
                st.markdown(
                    f"Company registry nº (KvK, the Dutch CIF) **{kvk}** — "
                    "[check it on the public registry]"
                    f"(https://www.kvk.nl/zoeken/?source=all&q={kvk})"
                )
        else:
            st.markdown("Not on the Dutch sponsor register.")
    with v2:
        st.markdown("**🧠 The text says** (the model's read)")
        if not row["is_enriched"]:
            st.markdown("_Not read yet._")
        else:
            st.markdown(ui.visa_label(row["visa_status"], is_enriched=True))
            if pd.notna(row["visa_confidence"]):
                st.progress(
                    float(row["visa_confidence"]),
                    text=f"confidence {row['visa_confidence']:.0%}",
                )
            if _txt(row["visa_reasoning"]):
                st.markdown(f"**Why:** {_txt(row['visa_reasoning'])}")
            if _txt(row["visa_evidence"]):
                st.markdown(f"**Verbatim evidence:** “{_txt(row['visa_evidence'])}”")

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

ui.page_footer()
