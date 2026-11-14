"""My Fit — rank every open posting against your CV, then deep-dive one.

Privacy: the CV lives in st.session_state only. It is never written to the
warehouse, a file, or logs; closing the tab discards it. The only thing that
ever leaves the session is the single posting + CV pair sent to the LLM when
you explicitly click the deep-dive button.
"""

from __future__ import annotations

import hashlib

import pandas as pd
import streamlit as st
from streamlit_app import limits, ui
from streamlit_app.cv_match import (
    CV_MATCH_SYSTEM_PROMPT,
    MAX_CV_CHARS,
    CVUnreadable,
    build_deep_dive_prompt,
    extract_skills,
    read_cv,
    score_jobs,
    useful_vocabulary,
)
from streamlit_app.db import require_marts, run_df, staging_available

from jmi_core.settings import get_settings
from jmi_core.text import strip_html
from jmi_enrichment.providers import get_provider

ui.configure_page("My Fit")
ui.page_header(
    title="My Fit",
    subtitle=(
        "Paste your CV and every open role gets scored on how much of its stack you "
        "already have — instantly, with no LLM call."
    ),
)
st.caption(
    "🔒 Your CV stays in this browser session: never stored, never logged, gone when you "
    "close the tab. Only the deep-dive button below sends anything to a model."
)

st.markdown(
    """
**How it works — two steps, and the first one is free.**

1. **Every open role gets scored** against the technologies found in your CV. This is
   plain set arithmetic, runs instantly, and costs nothing.
2. **Pick one role** and spend a single LLM call on a written read of your fit against
   that specific posting.

Only roles whose stack the LLM has already extracted can be scored, so the list grows
as coverage does.
"""
)

require_marts(
    "marts.FT_JOB_POSTING",
    missing="Connected, but no marts yet — run the pipeline, then `make dbt-build`.",
)

# --- CV input (session-only) -------------------------------------------------
up, paste = st.columns(2, gap="large")
# The inputs are keyed by a generation number so "Forget my CV" can empty them:
# an uploader cannot be cleared through session state, only replaced, and a CV
# still sitting in the text box would be read straight back in on the rerun.
generation = st.session_state.get("cv_generation", 0)
with up:
    uploaded = st.file_uploader(
        "Upload your CV", type=["pdf", "txt", "md"], key=f"cv_upload_{generation}"
    )
with paste:
    pasted = st.text_area(
        "…or paste it as text",
        height=120,
        placeholder="Paste your CV here",
        max_chars=MAX_CV_CHARS,
        key=f"cv_paste_{generation}",
    )

# Streamlit drops a page's widgets when you leave it, so the uploader and the
# text box are empty again on the way back from Find Jobs. The CV was already
# being kept in the session; it just was never read back, and every return
# trip meant uploading it again.
if uploaded is not None:
    try:
        cv_text = read_cv(uploaded.name, uploaded.getvalue())
    except CVUnreadable as exc:
        st.error(str(exc), icon=":material/error:")
        ui.page_footer()
        st.stop()
elif pasted.strip():
    cv_text = pasted
else:
    cv_text = st.session_state.get("cv_text", "")


def _forget_cv() -> None:
    for key in ("cv_text", "cv_skills", "cv_skills_for", "fit_answers"):
        st.session_state.pop(key, None)
    st.session_state["cv_generation"] = st.session_state.get("cv_generation", 0) + 1


if not cv_text.strip():
    ui.page_footer()
    st.stop()
st.session_state["cv_text"] = cv_text
cv_id = hashlib.sha256(cv_text.encode("utf-8")).hexdigest()

kept, forget = st.columns([4, 1], vertical_alignment="center")
kept.caption(
    f"Working from a CV of {len(cv_text):,} characters, held in this session only. "
    "It also ranks the list on **Find Jobs** while this tab stays open."
)
forget.button("Forget my CV", on_click=_forget_cv, width="stretch")

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

# Edits to the list survive leaving the page too, for as long as the CV is the
# same one; a different CV starts again from what is detected in it.
if st.session_state.get("cv_skills_for") == cv_id:
    known = set(vocab)
    default_skills = [s for s in st.session_state.get("cv_skills", []) if s in known]
else:
    default_skills = extract_skills(cv_text, vocab)
skills = st.multiselect(
    "Skills found in your CV (edit if something was missed)",
    options=vocab,
    default=default_skills,
    key=f"skills_{cv_id[:12]}",
    help="The vocabulary is every technology the LLM has extracted from real postings.",
)
st.session_state["cv_skills"] = skills
st.session_state["cv_skills_for"] = cv_id
if not skills:
    st.warning("No known skills detected — add some manually to rank the postings.")
    ui.page_footer()
    st.stop()

jobs = run_df(
    """
    select
        content_hash, title, company_name, country_code, seniority, salary_raw,
        source, source_url, english_sufficient, technologies, last_seen_at
    from marts.FT_JOB_POSTING
    -- Open data roles only: ranking a filled posting wastes the reader's time.
    where is_enriched and is_target_role and is_active and len(technologies) > 0
    """
)
LEVELS = ui.SENIORITY_LABELS
levels = st.pills(
    "Level",
    options=list(LEVELS),
    format_func=LEVELS.__getitem__,
    selection_mode="multi",
    default=list(LEVELS),
    help="The level each posting asks for, as the LLM read it. Untick what isn't you.",
)
jobs = jobs[jobs["seniority"].fillna("unknown").isin(levels)]

ranked = score_jobs(jobs, skills)
if ranked.empty:
    st.info("No open role with a parsed stack at the levels picked.")
    ui.page_footer()
    st.stop()
ranked["market"] = ranked["country_code"].map(ui.market_label)

st.markdown(f"##### Ranked matches — {len(ranked):,} open roles with a parsed stack")
st.caption(
    "**Score = the technologies you have, out of the ones the posting names plus one.** "
    "The extra one is the requirement a short posting didn't spell out: a quarter of "
    "these name a single technology, and without it any CV with that one scored 100%. "
    "Now 1 of 1 is 50% and 5 of 6 is 71%. Fields rather than skills — *analytics*, "
    "*BI*, *data science* — count on neither side. Only open roles whose stack the LLM "
    "has read can be ranked, so this list grows daily."
)

event = st.dataframe(
    ranked.assign(match_pct=100 * ranked["match_pct"])[
        [
            "title",
            "company_name",
            "market",
            "match_pct",
            "n_techs",
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
        "match_pct": ui.share_column("Match"),
        "n_techs": st.column_config.NumberColumn(
            "Stack",
            help=(
                "How many technologies the posting names, leaving out fields like "
                "'analytics'. The match is out of this plus one."
            ),
        ),
        "matched": st.column_config.ListColumn("You have"),
        "missing": st.column_config.ListColumn("You lack"),
        "english_sufficient": st.column_config.CheckboxColumn("EN ok"),
        "source_url": st.column_config.LinkColumn("Link", display_text="open"),
    },
)

# --- LLM tier: one-call deep-dive on the selected posting --------------------
rows = ui.selected_rows(event)
if not rows:
    st.info("Select a posting to unlock the LLM deep-dive.", icon=":material/touch_app:")
    ui.page_footer()
    st.stop()

job = ranked.iloc[rows[0]]
company = job["company_name"] if pd.notna(job["company_name"]) else "unknown company"
st.divider()
st.markdown(f"#### Deep-dive: {ui.md_text(job['title'])} — {ui.md_text(company)}")

settings = get_settings()
# One answer per (CV, posting), kept for the session: the call is rationed, and
# selecting another row or editing a skill used to throw the answer away.
answers: dict[str, str] = st.session_state.setdefault("fit_answers", {})
answer_key = f"{cv_id}:{job['content_hash']}"
budget_line = st.empty()

if answer_key not in answers and st.button(
    "Analyze my fit (1 LLM call)", type="primary", disabled=limits.llm_calls_left() == 0
):
    # The deep-dive reads better with the full text, but it is not required:
    # the extracted stack alone still gives the model something concrete. The
    # demo sample has no staging schema, and this path sits behind a button, so
    # nothing would have caught it raising on a fresh clone.
    description = None
    if staging_available():
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
    if not limits.spend_llm_call():
        st.warning(limits.budget_caption())
    else:
        with st.spinner("Reading your CV against the posting…"):
            try:
                answers[answer_key] = get_provider(settings).complete(
                    system=CV_MATCH_SYSTEM_PROMPT, user=prompt
                )
            except Exception as exc:
                st.error(
                    "The LLM call failed — most often the free tier's daily quota. "
                    f"Try again later. ({type(exc).__name__})"
                )

if answer_key in answers:
    st.markdown(ui.strip_md_images(answers[answer_key]))
    st.caption(
        "Written by a model from the posting and your CV. Check the gaps against the "
        "original posting before acting on them."
    )

budget_line.caption(
    f"One call to `{settings.llm_provider}` / `{settings.llm_model}` with this posting + "
    f"your CV, on a free tier, so calls are rationed. {limits.budget_caption()}"
)

ui.page_footer()
