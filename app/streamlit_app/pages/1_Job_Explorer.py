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
from streamlit_app.cv_match import match_share
from streamlit_app.db import require_marts, run_df, staging_available

from jmi_core.text import strip_html

ui.configure_page("Find Jobs")
ui.page_header(
    title="Find Jobs",
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
    # Most postings state no salary; this puts the ones that do first. The grid
    # shows salary as text (ui.add_salary_eur), so its header sorts as text.
    "Salary stated": "salary_raw is null, last_seen_at desc nulls last",
}

# A CV left on My Fit ranks this page too. Session-only, like the CV itself.
cv_skills: list[str] = st.session_state.get("cv_skills") or []
MY_FIT = "My fit"
sort_options = ([MY_FIT] if cv_skills else []) + list(ORDERINGS)
#: Rows fetched for the grid. Above every market's open roles put together, so
#: "sort by my fit" ranks all of them and not the newest slice.
GRID_ROWS = 2000

f1, f2, f3, f4, f5 = st.columns([2, 2, 2, 2, 1.4], gap="medium")
picked_markets = f1.multiselect("Market", market_options, default=[])
search = f2.text_input(
    "Title, company or technology",
    placeholder="engineer, dbt, Spotify…",
    max_chars=80,
)
picked_techs = f3.multiselect("Technologies (LLM-extracted)", techs)
picked_levels = f4.multiselect(
    "Seniority",
    list(ui.SENIORITY_LABELS),
    format_func=ui.SENIORITY_LABELS.__getitem__,
    help=(
        "The level the posting asks for, as the LLM read it. 'Not stated' is a "
        "posting that does not say — or one not read yet."
    ),
)
sort = f5.selectbox("Sort by", sort_options, index=sort_options.index("Last seen"))


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
if search.strip():
    # The placeholder has always offered "dbt", and a technology is not in a
    # title: so the term also matches a posting whose extracted stack names it.
    clauses.append(
        "(lower(title) like ? or lower(company_name) like ? "
        "or lower(array_to_string(technologies, ' | ')) like ?)"
    )
    params += [f"%{search.strip().lower()}%"] * 3
if picked_levels:
    clauses.append(f"coalesce(seniority, 'unknown') in ({', '.join('?' for _ in picked_levels)})")
    params += picked_levels
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
    order by {ORDERINGS.get(sort, ORDERINGS["Last seen"])}
    limit {GRID_ROWS}
    """,
    tuple(params),
)
# Counted, not inferred from the page of rows: with the limit at 1,000 and
# 1,125 roles open, this line used to announce "1,000 matching open roles".
total = int(
    run_df(f"select count(*) as n from marts.FT_JOB_POSTING {where}", tuple(params)).iloc[0]["n"]
)

if cv_skills:
    df["match"] = [match_share(techs_, cv_skills) for techs_ in df["technologies"]]
    df["match"] = pd.to_numeric(df["match"], errors="coerce") * 100
    if sort == MY_FIT:
        df = df.sort_values("match", ascending=False, na_position="last", kind="stable")
        df = df.reset_index(drop=True)

noun = "open roles" if active_only else "postings"
count_line = f"**{total:,}** matching {noun}"
if total > len(df):
    count_line += f", showing the first {len(df):,} — narrow the filters to see the rest"
count_col, fit_col = st.columns([3, 2], vertical_alignment="center")
count_col.caption(count_line + ".")
with fit_col:
    if cv_skills:
        st.caption(
            f"**My fit** scores each stack against the {len(cv_skills)} skills from your CV. "
            "Blank = no stack to score."
        )
    else:
        st.page_link(
            "pages/6_CV_Match.py",
            label="Add your CV to rank these by fit",
            icon=":material/target:",
        )

if df.empty:
    st.info(
        "Nothing matches these filters. Loosen one — *Stack read only* and "
        "*Written in English* are the two that cut the most.",
        icon=":material/filter_alt_off:",
    )
    ui.page_footer()
    st.stop()

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
        *(["match"] if cv_skills else []),
        "seniority",
        "technologies",
        "english_sufficient",
        "salary",
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
        match=ui.share_column(
            "My fit",
            help=(
                "The technologies from your CV, out of the ones this posting names "
                "plus one — the same score as My Fit. Blank = no stack to score."
            ),
        ),
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
    st.info("Select a row to open the posting card.", icon=":material/touch_app:")
    ui.page_footer()
    st.stop()

row = df.iloc[rows[0]]
st.divider()

head, links = st.columns([4, 1], gap="large")
with head:
    st.subheader(ui.md_text(row["title"]))
    location = _txt(row["location_raw"])
    st.markdown(
        f"**{ui.md_text(_txt(row['company_name']) or 'Unknown company')}** · "
        f"{ui.market_label(row['country_code'])}"
        + (f" · {ui.md_text(location)}" if location else "")
    )
    meta = [
        f"source: `{row['source']}`",
        f"first posted: {row['posted_at'].date()}" if pd.notna(row["posted_at"]) else None,
        f"last seen: {row['last_seen_at'].date()}" if pd.notna(row["last_seen_at"]) else None,
        f"salary: {ui.md_text(_txt(row['salary_raw']))}" if _txt(row["salary_raw"]) else None,
        f"type: {_txt(row['employment_type'])}" if _txt(row["employment_type"]) else None,
        f"remote: {_txt(row['remote_policy'])}" if _txt(row["remote_policy"]) else None,
    ]
    st.caption(" · ".join(m for m in meta if m))
with links:
    source_url = ui.safe_url(row["source_url"])
    if source_url:
        st.link_button("Open posting ↗", source_url, width="stretch")
    apply_url = ui.safe_url(row["apply_url"])
    if apply_url and apply_url != source_url:
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
        icon=":material/hourglass_top:",
    )
else:
    fit1, fit2 = st.columns(2, gap="large")
    with fit1:
        st.markdown("##### 🧰 The stack this role asks for")
        techs_list = _items(row["technologies"])
        if techs_list:
            st.markdown(" ".join(f":gray-badge[{ui.md_text(t)}]" for t in techs_list))
        else:
            st.caption("The LLM read this posting but found no named technologies in it.")
        bits = [
            f"**Role:** {ui.md_text(_txt(row['normalized_role']))}"
            if _txt(row["normalized_role"])
            else None,
            f"**Seniority:** {_txt(row['seniority'])}" if _txt(row["seniority"]) else None,
        ]
        if any(bits):
            st.markdown(" · ".join(b for b in bits if b))
        st.page_link(
            "pages/6_CV_Match.py",
            label="Score this stack against your CV",
            icon=":material/target:",
        )

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
            st.markdown("Working languages: " + ", ".join(ui.md_text(lang) for lang in langs))
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
                st.markdown(f"**Why:** {ui.md_text(_txt(row['visa_reasoning']))}")
            if _txt(row["visa_evidence"]):
                st.markdown(f"**Verbatim evidence:** “{ui.md_text(_txt(row['visa_evidence']))}”")

with st.expander("Full description (as scraped)"):
    # Descriptions live in staging, which the committed demo sample omits — the
    # text is megabytes and a committed file here is capped at 512 KB. This used
    # to raise a Catalog Error on a fresh clone, but only once a row was
    # selected, so no test reached it.
    if not staging_available():
        st.caption(
            "Full descriptions are not part of the committed demo sample. "
            "Connect a warehouse, or open the posting at its source above."
        )
    else:
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
