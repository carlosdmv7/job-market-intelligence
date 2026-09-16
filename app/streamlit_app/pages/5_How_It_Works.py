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
from streamlit_app.freshness import dbt_run_facts, sponsor_seed_facts

from jmi_core.settings import get_settings
from jmi_enrichment.prompts import SYSTEM_PROMPT as ENRICHMENT_PROMPT

_REPO_ROOT = Path(__file__).resolve().parents[3]
_EVAL_REPORT = _REPO_ROOT / "evals" / "report.json"
_GOLDEN_SET = _REPO_ROOT / "evals" / "golden_set.jsonl"

#: Below this many scored postings, headline metrics are noise dressed as
#: precision — macro-averaging over five classes needs support in each. An
#: "Accuracy 100%" computed on a handful of rows is exactly the unmeasured
#: confidence this page exists to avoid, so it is withheld instead.
_MIN_SCORED = 30

ui.configure_page("How It Works")
ui.page_header(
    title="⚙️ How It Works",
    subtitle="Every claim in this app is traceable. This page shows the machinery.",
)

# --- the daily pipeline ------------------------------------------------------
dbt_run = dbt_run_facts()
_tests = (
    f"{int(dbt_run['tests_passed'])}/{int(dbt_run['tests_total'])}"
    if dbt_run.get("tests_total")
    else "every"
)

st.markdown("#### 1 · A daily pipeline, at 0€")
st.markdown(
    "Every morning at 07:15 Amsterdam time, a GitHub Actions cron runs the whole thing: "
    f"collect postings → have an LLM read them → rebuild the tables → **{_tests} data "
    "tests must pass**. Nothing is hosted, nothing is paid for."
)

st.graphviz_chart(
    """
digraph pipeline {
  rankdir=LR;
  bgcolor="transparent";
  node [shape=box, style="rounded,filled", fontname="Helvetica", fontsize=10,
        color="#E4D9C4", fillcolor="#FDFAF4", fontcolor="#274C56", margin="0.14,0.09"];
  edge [color="#A8501F", arrowsize=0.6, penwidth=1.1];

  subgraph cluster_src {
    label="1 · Collect  (free APIs, daily)"; fontname="Helvetica"; fontsize=9;
    fontcolor="#6B7B80"; color="#E4D9C4"; style="rounded";
    adzuna [label="Adzuna\nNL · DE · ES"];
    jobtech [label="JobTech\nSE"];
    boards [label="Remote boards\nRemotive · Arbeitnow · RemoteOK"];
  }

  raw [label="raw.raw_job_postings\nappend-only log", fillcolor="#F5EFE3"];

  subgraph cluster_llm {
    label="2 · Read  (LLM, free tier)"; fontname="Helvetica"; fontsize=9;
    fontcolor="#6B7B80"; color="#E4D9C4"; style="rounded";
    llm [label="Gemini\n10 postings per request\n20 requests/day"];
    enr [label="raw.raw_job_enrichment\nstack · seniority · language", fillcolor="#F5EFE3"];
  }

  ind [label="IND sponsor register\nscraped monthly → dbt seed"];

  subgraph cluster_dbt {
    label="3 · Model  (dbt, tested)"; fontname="Helvetica"; fontsize=9;
    fontcolor="#6B7B80"; color="#E4D9C4"; style="rounded";
    staging [label="staging"];
    dedup [label="de-duplicate\nby content hash"];
    marts [label="marts\nFT_JOB_POSTING\nFT_JOB_SNAPSHOT_DAILY", fillcolor="#F5EFE3"];
  }

  app [label="This app", fillcolor="#F5EFE3", color="#D96C2C"];

  adzuna -> raw; jobtech -> raw; boards -> raw;
  raw -> llm [label="  not yet read", fontsize=8, fontcolor="#6B7B80"];
  llm -> enr;
  raw -> staging; enr -> staging; ind -> staging;
  staging -> dedup -> marts -> app;
}
"""
)

with st.expander("Why postings are never overwritten"):
    st.markdown(
        """
Each sighting of a posting is stored as a new **observation**, not an update. Seeing
the same job again tomorrow adds a row rather than replacing one.

That is what makes two things possible: the trend charts (a posting's daily presence
*is* the history) and the open/closed flag (a job we stop seeing has almost certainly
been filled — boards delete rather than close). The cost is a bigger table; the benefit
is that no question about the past becomes unanswerable later.

Cross-source duplicates — the same job on three boards — collapse in dbt via a hash of
its content, so a job posted widely is not counted three times.
"""
    )

# --- the two signals ----------------------------------------------------------
st.markdown("#### 2 · Two kinds of signal, never mixed")
st.markdown(
    "Some facts can be **looked up**; others can only be **read out of prose**. The app "
    "keeps them apart everywhere, and labels which is which, because they fail "
    "differently: a lookup is either right or missing, while a reading can be confidently "
    "wrong. Visa sponsorship is the clearest example — it is the one field where both "
    "kinds are available for the same question."
)
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
- **Free-tier aware** — the quota is counted in *requests*, not tokens (a
  measured 20/day/model), so ten postings ride in each one: the same budget
  reads 200 postings a day instead of 20. Each response echoes the index of the
  posting it answers and is matched by that index, never by position — a short
  or reordered reply would otherwise attach one job's stack to another silently.
  A circuit breaker stops the batch after 5 consecutive provider failures (a
  dead quota), and results are upserted in chunks so an interrupted run loses
  almost nothing. The queue is data roles only, freshest sighting first.
"""
    )

# --- live coverage -------------------------------------------------------------
require_marts("marts.FT_JOB_POSTING", missing="No marts yet — run the pipeline first.")
# Open data roles, not every row ever collected. The warehouse keeps closed
# postings and off-target jobs for the trend charts, and dividing by those
# reported 8% coverage for a pipeline that had read a third of what the app
# actually shows. The denominator was the misleading part, not the number.
cov = run_df(
    """
    select
        coalesce(country_code, 'Remote/global')                    as market,
        count(*)                                                   as open_roles,
        count(*) filter (where is_enriched)                        as enriched,
        round(100.0 * count(*) filter (where is_enriched)
              / nullif(count(*), 0), 1)                            as pct
    from marts.FT_JOB_POSTING
    where is_target_role and is_active
    group by 1 order by open_roles desc
    """
)
st.markdown("##### Live enrichment coverage")
st.caption(
    "Open data roles only — the rows the app actually offers you. The warehouse also "
    "holds closed postings and off-target jobs, kept for the trend charts; counting "
    "those in the denominator is how this number once read 8% for a pipeline that had "
    "read a third of what you can see."
)
st.dataframe(
    cov,
    width="stretch",
    hide_index=True,
    column_config={
        "market": st.column_config.TextColumn("Market"),
        "open_roles": st.column_config.NumberColumn("Open roles"),
        "enriched": st.column_config.NumberColumn("LLM-read"),
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


#: Which golden-set field holds the label for each eval target.
_TRUTH_FIELD = {"english": "english_sufficient_true", "visa": "visa_status_true"}


def _golden_progress(target: str) -> tuple[int, int]:
    """(labelled, total) for one target — read from the committed golden set.

    Per target, because the two are labelled independently: a row answered for
    English is not a row answered for visas, and counting them together would
    overstate how much of the set is actually usable for the score shown.
    """
    if not _GOLDEN_SET.exists():
        return 0, 0
    field = _TRUTH_FIELD.get(target, "english_sufficient_true")
    total = labelled = 0
    for line in _GOLDEN_SET.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        total += 1
        try:
            if json.loads(line).get(field) is not None:
                labelled += 1
        except json.JSONDecodeError:
            continue
    return labelled, total


report = _eval_report()
_target = (report or {}).get("target", "english")
_headline = (report or {}).get("target_headline", "Classifier")
labelled, total = _golden_progress(_target)

with st.expander("Why the headline metric moved from visa sponsorship to English"):
    st.markdown(
        """
The harness was built around the visa field, because visa sponsorship was the
product. The measurement is what retired it: across 730 postings the classifier
had read, its own output was `unclear` 583 times and `explicit_yes` **once**.

Fourteen hand labels then scored 0.000 precision on `explicit_yes` — not because
the model failed, but because a class that rare cannot be measured. No amount of
further labelling fixes that; the corpus simply does not contain the signal.

So the target moved to a field that *is* measurable and that changes a decision:
**can someone who speaks English but not the local language do this job?** The
corpus splits roughly 355 / 330 / 45 on it. The visa labels are kept and
`--target visa` still scores them — a retired metric is part of the record, not
an embarrassment to delete.
"""
    )

if report and report.get("n", 0) >= _MIN_SCORED:
    e1, e2, e3, e4 = st.columns(4)
    e1.metric(
        "Accuracy",
        f"{report['accuracy']:.0%}",
        help=f"{_headline}, on {report['n']} scored postings.",
    )
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
            "class": st.column_config.TextColumn("Class"),
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
    scored = report.get("n", 0) if report else 0
    st.info(
        f"**The harness is built and wired into CI; the labels are in progress** — "
        f"{labelled} of {total} sampled postings labelled, {scored} of them scored "
        f"so far (a label only scores once the pipeline has enriched that posting). "
        f"Headline accuracy appears here at {_MIN_SCORED} scored postings: a "
        "percentage computed on a handful of rows would be exactly the unmeasured "
        "confidence this section exists to avoid."
    )
else:
    st.info(
        "The eval harness ships with this repo (`evals/`), but no golden set has "
        "been sampled into this checkout yet."
    )

# --- provenance the other pages do not need ----------------------------------
st.divider()
st.markdown("#### 5 · Provenance")
st.caption(
    "These used to sit in the strip at the top of every page. They are proof the machinery "
    "is wired correctly, which is a different job from helping you pick a posting — so they "
    "live here now."
)

seed = sponsor_seed_facts()
p1, p2, p3 = st.columns(3)
p1.metric(
    "IND register entries",
    f"{int(seed['sponsors']):,}" if seed.get("sponsors") else "—",
    help=(
        "Employers on the Dutch recognised-sponsor list, scraped into a committed dbt "
        "seed. IND republishes it monthly."
    ),
)
p2.metric(
    "Register snapshot",
    str(seed.get("refreshed_at") or "—"),
    help="When that seed was last refreshed from IND.",
)
p3.metric(
    "dbt tests, last run",
    _tests if dbt_run.get("tests_total") else "no run recorded",
    help=(
        "Read from the recorded `dbt build`, not hardcoded. A failing test fails the "
        "pipeline, so the marts either passed or did not update."
    ),
)

# --- agent guardrails ----------------------------------------------------------
st.markdown("#### 6 · Ask the Data — guardrails")
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

The first three are checks in this repo's code, so they fail the way code
fails. The fourth is the one that holds when the other three are wrong, so it
is not this app's promise to keep: the connection is opened read-only and
**MotherDuck refuses the write server-side**. The token itself is read/write,
because the free plan issues no other kind — which is exactly why the
guarantee is placed on the connection instead. There is no fallback to a
writable connection; without a read-only one the app serves the committed
sample and says so.
"""
    )

st.info(
    "The full source (pipeline, dbt models, prompts, tests) is public: "
    "[github.com/carlosdmv7/job-market-intelligence]"
    "(https://github.com/carlosdmv7/job-market-intelligence)"
)

ui.page_footer()
