"""How It Works — the pipeline, the two visa signals, and the LLM's rubric.

Transparency page: shows the *actual* system prompt the classifier runs with
(imported from the enrichment package, so it can never drift from reality),
live enrichment coverage, and the guardrails on the text-to-SQL agent.

Each section leads with one visible sentence; the rationale and detail sit in
an expander. Someone skimming gets the shape of the whole page in one
scroll; someone auditing a specific claim clicks to see it.
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import streamlit as st
from streamlit_app import ui
from streamlit_app.db import require_marts, run_df

from jmi_core.settings import get_settings
from jmi_enrichment.prompts import SYSTEM_PROMPT as ENRICHMENT_PROMPT

_REPO_ROOT = Path(__file__).resolve().parents[3]
_EVAL_REPORT = _REPO_ROOT / "evals" / "report.json"
_GOLDEN_SET = _REPO_ROOT / "evals" / "golden_set.jsonl"

ui.configure_page("How It Works")
ui.page_header(
    title="⚙️ How It Works",
    subtitle="Every claim in this app is traceable. This page shows the machinery.",
)

# --- the daily pipeline ------------------------------------------------------
st.markdown("#### 1 · A daily pipeline, at 0€")
st.markdown(
    "Every morning (07:15 Amsterdam) a GitHub Actions cron runs the full "
    "pipeline — the same Prefect-instrumented flows a paid worker would run: "
    "ingest → LLM enrichment → `dbt build`, and 45 data tests must pass, every day."
)
with st.expander("Show the pipeline diagram"):
    st.markdown(
        """
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

# --- the two signals ----------------------------------------------------------
st.markdown("#### 2 · Two visa signals, deliberately separate")
c1, c2 = st.columns(2, gap="large")
with c1:
    st.markdown(
        """
##### 🏛️ Deterministic (primary)
Company name → normalized → matched against the **official IND register**
of employers legally authorised to sponsor a NL highly-skilled-migrant visa.

- A match carries the company's **KvK number**, verifiable on the public
  Chamber of Commerce register.
- Works for **every** posting, enriched or not.
"""
    )
with c2:
    st.markdown(
        """
##### 🧠 LLM read of the text (secondary)
The posting text is classified into a **closed enum**
(`explicit_yes / likely_yes / unclear / likely_no / explicit_no`) with a
confidence score, a **verbatim evidence quote**, and the model + prompt
version that produced it — shown on every job card.

`explicit_no` is kept distinct from `unclear`: *"we do not sponsor"* is a
strong negative filter, not an absence of signal.
"""
    )
st.caption(
    "Swedish postings carry the employer's organisationsnummer (Bolagsverket) in "
    "the raw payload — the same audit-trail idea, one register per market."
)

# --- the actual prompt --------------------------------------------------------
st.markdown("#### 3 · How the classifier thinks — the actual prompt")
settings = get_settings()
st.caption(
    f"Live configuration: provider `{settings.llm_provider}` · model `{settings.llm_model}` · "
    f"prompt version `{settings.enrichment_prompt_version}`. Imported straight from the "
    "enrichment package below — this is the exact prompt in production, never a copy."
)
with st.expander("Show the full system prompt"):
    st.code(ENRICHMENT_PROMPT, language="text")
with st.expander("Why the prompt is designed this way"):
    st.markdown(
        """
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

# --- live coverage -------------------------------------------------------------
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

# --- evals ---------------------------------------------------------------------
st.markdown("#### 4 · Is the classifier any good? — measured, not asserted")
st.markdown(
    "The classifier is scored against a **hand-labelled golden set**, never "
    'asserted from vibes — the committed contract for what "correct" means '
    "here ([ADR 0006](https://github.com/carlosdmv7/job-market-intelligence/blob/main/docs/adr/0006-llm-evaluation.md))."
)
with st.expander('What "correct" means here'):
    st.markdown(
        """
The ground truth answers *"does this posting's text state or imply
sponsorship?"* — never *"can this employer sponsor?"*. That second question is
already answered, deterministically and better, by the IND register join above.
CI replays **recorded** production responses, so a red eval means the prompt or
the code changed, never that the model had a bad morning.
"""
    )


def _eval_report() -> dict | None:
    if not _EVAL_REPORT.exists():
        return None
    try:
        return json.loads(_EVAL_REPORT.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _golden_progress() -> tuple[int, int]:
    """(labelled, total) — read from the committed golden set."""
    if not _GOLDEN_SET.exists():
        return 0, 0
    total = labelled = 0
    for line in _GOLDEN_SET.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        total += 1
        try:
            if json.loads(line).get("visa_status_true") is not None:
                labelled += 1
        except json.JSONDecodeError:
            continue
    return labelled, total


report = _eval_report()
labelled, total = _golden_progress()

if report:
    e1, e2, e3, e4 = st.columns(4)
    e1.metric("Accuracy", f"{report['accuracy']:.0%}", help=f"On {report['n']} scored postings.")
    e2.metric(
        "Macro F1",
        f"{report['macro_f1']:.2f}",
        help="Unweighted mean over classes — the rare ones count as much as `unclear`.",
    )
    e3.metric("Macro recall", f"{report['macro_recall']:.2f}")
    e4.metric("Golden set", f"{labelled}/{total} labelled")

    per_class = pd.DataFrame(report["per_class"]).T.reset_index(names="class")
    st.markdown("##### Per-class performance")
    ui.table(
        per_class[["class", "support", "precision", "recall", "f1"]],
        column_config={
            "class": st.column_config.TextColumn("Visa status"),
            "support": st.column_config.NumberColumn(
                "Support", help="How many labelled postings truly are this class."
            ),
            "precision": st.column_config.NumberColumn("Precision", format="%.2f"),
            "recall": st.column_config.NumberColumn("Recall", format="%.2f"),
            "f1": st.column_config.NumberColumn("F1", format="%.2f"),
        },
    )

    with st.expander("Confusion matrix (rows = truth, columns = prediction)"):
        st.dataframe(pd.DataFrame(report["confusion"]).T, width="stretch")

    agreement = report.get("agreement") or {}
    if agreement:
        st.markdown("##### Agreement with the deterministic IND signal")
        st.caption(
            "A diagnostic, not a score. A recognised sponsor whose ad never mentions "
            "visas is the ordinary case — that is exactly why the register is the "
            "primary signal. The number worth watching is the first one: the LLM "
            "claiming sponsorship at an employer that legally cannot sponsor."
        )
        a1, a2 = st.columns(2)
        confirmed = agreement.get("llm_positive_confirmed_by_register")
        stated = agreement.get("register_positive_stated_in_text")
        a1.metric(
            "LLM positives confirmed by the register",
            f"{confirmed:.0%}" if confirmed is not None else "—",
            help=f"Of {agreement.get('llm_positive', 0)} postings the LLM called sponsoring.",
        )
        a2.metric(
            "Recognised sponsors that say so in the text",
            f"{stated:.0%}" if stated is not None else "—",
            help=f"Of {agreement.get('ind_positive', 0)} postings at recognised sponsors.",
        )
elif total:
    st.info(
        f"**The harness is built and wired into CI; the labels are in progress** — "
        f"{labelled} of {total} sampled postings labelled so far. Scores appear here "
        "as soon as the golden set has labelled rows. Showing a number before then "
        "would be exactly the unmeasured confidence this section exists to avoid."
    )
else:
    st.info(
        "The eval harness ships with this repo (`evals/`), but no golden set has "
        "been sampled into this checkout yet."
    )

# --- agent guardrails ----------------------------------------------------------
st.markdown("#### 5 · Ask the Data — guardrails")
st.markdown(
    "The natural-language agent translates a question into **one** SQL query, "
    "which is validated before execution — and the generated SQL is always "
    "shown, so you can audit exactly what ran."
)
with st.expander("The four checks"):
    st.markdown(
        """
1. **SELECT/WITH-only** — a single statement; any DDL/DML keyword is rejected.
2. **marts schema only** — the prompt never exposes raw or staging.
3. **Forced LIMIT** — capped at 500 rows.
4. **Read-only connection** — even a guard bypass cannot write.
"""
    )

st.info(
    "The full source (pipeline, dbt models, prompts, tests) is public: "
    "[github.com/carlosdmv7/job-market-intelligence]"
    "(https://github.com/carlosdmv7/job-market-intelligence)"
)

ui.page_footer()
