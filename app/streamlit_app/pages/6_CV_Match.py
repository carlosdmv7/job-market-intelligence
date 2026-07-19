"""CV Match — rank every enriched posting against your CV, then deep-dive one.

Privacy: the CV lives in st.session_state only. It is never written to the
warehouse, a file, or logs; closing the tab discards it. The only thing that
ever leaves the session is the single posting + CV pair sent to the LLM when
you explicitly click the deep-dive button.
"""

from __future__ import annotations

import io

import pandas as pd
import streamlit as st
from streamlit_app import ui
from streamlit_app.cv_match import (
    CV_MATCH_SYSTEM_PROMPT,
    build_deep_dive_prompt,
    extract_skills,
    score_jobs,
    useful_vocabulary,
)
from streamlit_app.db import require_marts, run_df

from jmi_core.settings import get_settings
from jmi_core.text import strip_html
from jmi_enrichment.providers import get_provider

st.set_page_config(page_title="CV Match", page_icon="🎯", layout="wide")
st.title("🎯 CV Match")
st.caption(
    "Upload or paste your CV → every LLM-enriched posting gets a skill-overlap score, "
    "free and instant. Then spend **one** LLM call on the posting you care about."
)
st.info(
    "🔒 **Your CV never leaves this session.** It is not stored anywhere; closing the "
    "tab discards it. Only the explicit deep-dive button sends it (with one posting) "
    "to the LLM.",
    icon="🔒",
)

require_marts(
    "marts.FT_JOB_POSTING",
    missing="Connected, but no marts yet — run the pipeline, then `make dbt-build`.",
)

# --- CV input (session-only) -------------------------------------------------
up, paste = st.columns(2, gap="large")
with up:
    uploaded = st.file_uploader("Upload your CV", type=["pdf", "txt", "md"])
with paste:
    pasted = st.text_area("…or paste it as text", height=120, placeholder="Paste your CV here")

cv_text = ""
if uploaded is not None:
    if uploaded.name.lower().endswith(".pdf"):
        from pypdf import PdfReader  # lazy: only needed for PDF uploads

        reader = PdfReader(io.BytesIO(uploaded.getvalue()))
        cv_text = "\n".join(page.extract_text() or "" for page in reader.pages)
    else:
        cv_text = uploaded.getvalue().decode("utf-8", errors="replace")
elif pasted.strip():
    cv_text = pasted

if not cv_text.strip():
    st.stop()
st.session_state["cv_text"] = cv_text

# --- deterministic tier: skill extraction + overlap ranking ------------------
vocab = useful_vocabulary(
    run_df(
        """
        select tech, count(*) as n from (
            select unnest(technologies) as tech from marts.FT_JOB_POSTING
        ) group by 1 order by n desc
        """
    )["tech"].tolist()
)

detected = extract_skills(cv_text, vocab)
skills = st.multiselect(
    "Skills found in your CV (edit if something was missed)",
    options=vocab,
    default=detected,
    help="The vocabulary is every technology the LLM has extracted from real postings.",
)
if not skills:
    st.warning("No known skills detected — add some manually to rank the postings.")
    st.stop()

jobs = run_df(
    """
    select
        content_hash, title, company_name, country_code, seniority, salary_raw,
        source, source_url, english_sufficient, technologies, last_seen_at
    from marts.FT_JOB_POSTING
    where is_enriched and len(technologies) > 0
    """
)
ranked = score_jobs(jobs, skills)
ranked["market"] = ranked["country_code"].map(ui.market_label)

st.markdown(f"##### Ranked matches — {len(ranked):,} postings with extracted technologies")
st.caption(
    "Score = share of the posting's technologies your CV covers. Only enriched postings "
    "are rankable; coverage grows daily as the pipeline enriches more."
)

event = st.dataframe(
    ranked[
        [
            "title",
            "company_name",
            "market",
            "match_pct",
            "matched",
            "missing",
            "english_sufficient",
            "source_url",
        ]
    ],
    width="stretch",
    hide_index=True,
    on_select="rerun",
    selection_mode="single-row",
    height=420,
    column_config={
        "title": st.column_config.TextColumn("Title", width="large"),
        "company_name": st.column_config.TextColumn("Company"),
        "market": st.column_config.TextColumn("Market"),
        "match_pct": st.column_config.ProgressColumn(
            "Match", format="percent", min_value=0.0, max_value=1.0
        ),
        "matched": st.column_config.ListColumn("You have"),
        "missing": st.column_config.ListColumn("You lack"),
        "english_sufficient": st.column_config.CheckboxColumn("EN ok"),
        "source_url": st.column_config.LinkColumn("Link", display_text="open"),
    },
)

# --- LLM tier: one-call deep-dive on the selected posting --------------------
rows = event.selection.rows if event.selection else []
if not rows:
    st.info("👆 Select a posting to unlock the LLM deep-dive.")
    st.stop()

job = ranked.iloc[rows[0]]
st.divider()
st.markdown(f"#### Deep-dive: {job['title']} — {job['company_name'] or 'unknown company'}")

settings = get_settings()
st.caption(
    f"One call to `{settings.llm_provider}` / `{settings.llm_model}` with this posting + "
    "your CV. Free tier: if the daily quota is spent you'll get an error — try tomorrow."
)

if st.button("Analyze my fit (1 LLM call)", type="primary"):
    desc = run_df(
        "select description_raw from staging.stg_job_postings where content_hash = ? limit 1",
        (job["content_hash"],),
    )
    description = strip_html(desc.iloc[0, 0]) if not desc.empty else None
    prompt = build_deep_dive_prompt(
        cv_text,
        title=job["title"],
        company=job["company_name"] if pd.notna(job["company_name"]) else None,
        description=description,
        technologies=list(job["technologies"]),
    )
    with st.spinner("Reading your CV against the posting…"):
        try:
            answer = get_provider(settings).complete(system=CV_MATCH_SYSTEM_PROMPT, user=prompt)
        except Exception as exc:
            st.error(f"The LLM call failed (likely a spent free-tier quota): {exc}")
            st.stop()
    st.markdown(answer)
