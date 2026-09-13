"""The freshness strip's data — every value read, none hardcoded.

Each fact is sourced from the thing it describes:

* postings / coverage / last run  → the marts themselves;
* recognised sponsors             → the dbt seed and its committed meta sidecar;
* dbt tests                       → ``meta.pipeline_run``, one row appended
  by the daily pipeline (``run_results.json`` locally).

If a source is unavailable the fact says so ("unknown") rather than quietly
disappearing or being replaced by a plausible constant — a freshness header
that can silently lie is worse than none.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd
import streamlit as st

from streamlit_app.db import run_df
from streamlit_app.theme import Fact, Tone

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SEED_META = _REPO_ROOT / "dbt" / "jmi" / "seeds" / "recognised_sponsors.meta.json"
_SEED_CSV = _REPO_ROOT / "dbt" / "jmi" / "seeds" / "recognised_sponsors.csv"
# Local dev has the real dbt artifact; the deployed app reads meta.pipeline_run.
_RUN_RESULTS = _REPO_ROOT / "dbt" / "jmi" / "target" / "run_results.json"


def _age(ts: Any) -> tuple[str, Tone]:
    """Human age + tone. Daily pipeline, so >48h stale is a real problem."""
    if ts is None or pd.isna(ts):
        return "unknown", "bad"
    moment = pd.Timestamp(ts)
    moment = moment.tz_localize(UTC) if moment.tzinfo is None else moment.tz_convert(UTC)
    hours = (datetime.now(UTC) - moment.to_pydatetime()).total_seconds() / 3600
    if hours < 1:
        return "just now", "good"
    if hours < 36:
        return f"{int(hours)}h ago", "good"
    days = int(hours // 24)
    return f"{days}d ago", "warn" if days <= 3 else "bad"


@st.cache_data(ttl=600, show_spinner=False)
def _warehouse_facts() -> dict[str, Any]:
    row = run_df(
        """
        select
            count(*) filter (where is_target_role and is_active)   as open_roles,
            count(*) filter (where is_target_role and is_active
                             and len(technologies) > 0)            as with_stack,
            count(distinct company_name) filter
                (where is_target_role and is_active)               as companies,
            max(last_seen_at)                                      as last_run
        from marts.FT_JOB_POSTING
        """
    ).iloc[0]
    # Deliberately *not* count(*) over the whole table. The warehouse holds
    # 12.7k rows, most of them closed roles and off-target jobs kept for
    # history, so a corpus-wide coverage ratio reported 8% and read as "this
    # barely works". Measured against what the app actually shows, the same
    # pipeline is at a third. The denominator was the misleading part.
    open_roles = int(row.open_roles)
    return {
        "open_roles": open_roles,
        "with_stack": int(row.with_stack),
        "companies": int(row.companies),
        "stack_coverage": (int(row.with_stack) / open_roles) if open_roles else 0.0,
        "last_run": row.last_run,
    }


@st.cache_data(ttl=3600, show_spinner=False)
def sponsor_seed_facts() -> dict[str, Any]:
    """Sponsor count + refresh date from the committed seed and its sidecar.

    Public because How It Works renders it: engineering provenance belongs on the
    page that exists to show the machinery, not in the strip on top of every page.
    """
    meta: dict[str, Any] = {}
    if _SEED_META.exists():
        try:
            meta = json.loads(_SEED_META.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            meta = {}
    rows = meta.get("row_count")
    if rows is None and _SEED_CSV.exists():
        # Fall back to counting the file rather than showing nothing.
        with _SEED_CSV.open(encoding="utf-8") as fh:
            rows = max(sum(1 for _ in fh) - 1, 0)
    return {"sponsors": rows, "refreshed_at": meta.get("refreshed_at")}


@st.cache_data(ttl=600, show_spinner=False)
def dbt_run_facts() -> dict[str, Any]:
    """The last recorded pipeline run.

    Local dev has the real dbt artifact; a deployed app has only the warehouse,
    where the pipeline appends one row per run (see `jmi_flows.dbt_status`).
    Reading it from there is what lets the pipeline stop committing a status
    file to `main` every single day.
    """
    from importlib import import_module

    if _RUN_RESULTS.exists():
        try:
            summarize = import_module("jmi_flows.dbt_status").summarize
            return summarize(json.loads(_RUN_RESULTS.read_text(encoding="utf-8")))
        except (OSError, json.JSONDecodeError, ImportError, KeyError):
            pass
    try:
        df = run_df(
            """
            select tests_total, tests_passed, models_total, models_passed,
                   dbt_version, recorded_at, conclusion
            from meta.pipeline_run
            where tests_total is not null
            order by recorded_at desc
            limit 1
            """
        )
    except Exception:
        return {}
    return {} if df.empty else df.iloc[0].to_dict()


def header_facts() -> list[Fact]:
    """Assemble the strip. Never raises: a broken source degrades to 'unknown'."""
    facts: list[Fact] = []

    try:
        wh = _warehouse_facts()
    except Exception:
        # Unreachable warehouse, missing marts, driver error — the page itself
        # diagnoses that properly via require_marts(); the strip just abstains.
        wh = {}

    if wh:
        age, tone = _age(wh["last_run"])
        facts.append(
            Fact(
                "last pipeline run",
                age,
                tone,
                help="Newest `last_seen_at` in the marts. The pipeline runs daily at 07:15 Amsterdam.",
            )
        )
        facts.append(
            Fact(
                "open data roles",
                f"{wh['open_roles']:,}",
                help=(
                    "Data, analytics and ML roles still visible on their source board. "
                    "Closed ones are kept for the trend charts but excluded here."
                ),
            )
        )
        facts.append(Fact("companies hiring", f"{wh['companies']:,}"))
        facts.append(
            Fact(
                "with tech stack read",
                f"{wh['stack_coverage']:.0%}",
                "warn" if wh["stack_coverage"] < 0.5 else "good",
                help=(
                    "Share of open data roles whose technologies the LLM has extracted — "
                    "the field that powers stack search and CV matching. Capped by the "
                    "Gemini free tier (a measured 20 requests/day/model), so it grows "
                    "daily. Unread is **not** the same as 'no match'."
                ),
            )
        )
    else:
        facts.append(Fact("warehouse", "unreachable", "bad"))

    # The IND seed size and the dbt test tally used to sit here. Both are
    # engineering provenance — proof the thing is wired correctly — and neither
    # helps someone deciding which job to open. They live on How It Works now,
    # next to the rest of the evidence.
    return facts
