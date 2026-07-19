"""How It Works — the pipeline, the two visa signals, and the LLM's rubric.

Transparency page: shows the *actual* system prompt the classifier runs with
(imported from the enrichment package, so it can never drift from reality),
live enrichment coverage, and the guardrails on the text-to-SQL agent.
"""

from __future__ import annotations

import streamlit as st
from streamlit_app.db import require_marts, run_df

from jmi_core.settings import get_settings
from jmi_enrichment.prompts import SYSTEM_PROMPT as ENRICHMENT_PROMPT

st.set_page_config(page_title="How It Works", page_icon="⚙️", layout="wide")
st.title("⚙️ How It Works")
st.caption("Every claim in this app is traceable. This page shows the machinery.")

# --- the daily pipeline ----------------------------------------------------
st.markdown("#### 1 · A daily pipeline, at 0€")
st.markdown(
    """
Every morning (07:15 Amsterdam) a GitHub Actions cron runs the full pipeline —
the same Prefect-instrumented flows you would deploy on a worker:

```
Adzuna NL/DE/ES + JobTech SE + free remote boards ──► raw.raw_job_postings   (append-only)
IND recognised-sponsor register (scraper → dbt seed)                          (monthly)
LLM enrichment (Gemini free tier, ~50 postings/day) ──► raw.raw_job_enrichment
dbt build: staging → dedup → marts  (45 data tests must pass, every day)
```

Postings are **append-only observations**: re-seeing a posting on a new day feeds
the daily snapshot mart (`FT_JOB_SNAPSHOT_DAILY`), which is where the trends
come from. Cross-source duplicates collapse via a content hash in dbt.
"""
)

# --- the two signals -------------------------------------------------------
st.markdown("#### 2 · Two visa signals, deliberately separate")
c1, c2 = st.columns(2, gap="large")
with c1:
    st.markdown(
        """
##### 🏛️ Deterministic (primary)
Company name → normalized → matched against the **official IND register**
of employers legally authorised to sponsor a NL highly-skilled-migrant visa.

- A match carries the company's **KvK number** — verifiable on the public
  Chamber of Commerce register. No hallucinations possible.
- Works for **every** posting, enriched or not.
- Swedish postings carry the employer's **organisationsnummer**
  (Bolagsverket) in the raw payload — the same audit-trail idea.
"""
    )
with c2:
    st.markdown(
        """
##### 🧠 LLM read of the text (secondary)
The posting text is classified into a **closed enum**
(`explicit_yes / likely_yes / unclear / likely_no / explicit_no`) with:

- a **confidence** score (0 to 1),
- a **verbatim evidence quote** in the original language,
- a one-sentence **reasoning**, and
- the **model + prompt version** that produced it (shown on every job card).

`explicit_no` is kept distinct from `unclear` on purpose: *"we do not sponsor"*
is a strong negative filter, not an absence of signal.
"""
    )

# --- the actual prompt -----------------------------------------------------
st.markdown("#### 3 · How the classifier thinks — the actual prompt")
settings = get_settings()
st.caption(
    f"Live configuration: provider `{settings.llm_provider}` · model `{settings.llm_model}` · "
    f"prompt version `{settings.enrichment_prompt_version}`. The text below is imported "
    "from the enrichment package — it is the exact system prompt in production."
)
with st.expander("Show the full system prompt"):
    st.code(ENRICHMENT_PROMPT, language="text")
st.markdown(
    """
Design choices worth noting:

- **Closed vocabularies, generated from the schema** — the JSON the model must
  return enumerates the same enums the warehouse stores, so values never drift.
- **Verbatim evidence required** — if the model claims sponsorship, it must quote
  the sentence that says so. That quote is displayed, not summarized.
- **"Unknown" is a valid answer** — the rubric explicitly prefers `unknown`/null +
  low confidence over guessing.
- **Free-tier aware** — ~50 postings/day fit the Gemini free quota; a circuit
  breaker stops the batch after 5 consecutive provider failures (a dead quota),
  and results are upserted in chunks of 10 so an interrupted run loses almost
  nothing. Coverage accumulates daily, NL first.
"""
)

# --- live coverage ---------------------------------------------------------
require_marts("marts.FT_JOB_POSTING", missing="No marts yet — run the pipeline first.")
cov = run_df(
    """
    select
        coalesce(country_code, 'Remote/global') as market,
        count(*) as postings,
        count(*) filter (where is_enriched) as enriched,
        round(100.0 * count(*) filter (where is_enriched) / count(*), 1) as pct
    from marts.FT_JOB_POSTING
    group by 1 order by postings desc
    """
)
st.markdown("##### Live enrichment coverage")
st.dataframe(
    cov,
    width="stretch",
    hide_index=True,
    column_config={
        "market": st.column_config.TextColumn("Market"),
        "postings": st.column_config.NumberColumn("Postings"),
        "enriched": st.column_config.NumberColumn("LLM-enriched"),
        "pct": st.column_config.NumberColumn("Coverage %", format="%.1f%%"),
    },
)

# --- agent guardrails ------------------------------------------------------
st.markdown("#### 4 · Ask the Data — guardrails")
st.markdown(
    """
The natural-language agent translates a question into **one** SQL query, then a
guard validates it before execution:

1. **SELECT/WITH-only** — a single statement; any DDL/DML keyword is rejected.
2. **marts schema only** — the prompt never exposes raw or staging.
3. **Forced LIMIT** — capped at 500 rows.
4. **Read-only connection** — even a guard bypass cannot write.

The generated SQL is always displayed before the results, so you can audit
what was actually run.
"""
)

st.info(
    "The full source (pipeline, dbt models, prompts, tests) is public: "
    "[github.com/carlosdmv7/job-market-intelligence]"
    "(https://github.com/carlosdmv7/job-market-intelligence)"
)
