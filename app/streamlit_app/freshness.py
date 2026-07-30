"""The freshness strip's data — every value read, none hardcoded.

Each fact is sourced from the thing it describes:

* postings / coverage / last run  → the marts themselves;
* recognised sponsors             → the dbt seed and its committed meta sidecar;
* dbt tests                       → ``run_results.json``, distilled into
  ``docs/status/pipeline.json`` by the daily pipeline.

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
# Local dev has the real dbt artifact; the deployed app only has the committed
# distillation of it (target/ is gitignored). Try both, in that order.
_RUN_RESULTS = _REPO_ROOT / "dbt" / "jmi" / "target" / "run_results.json"
_STATUS_FILE = _REPO_ROOT / "docs" / "status" / "pipeline.json"


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
            count(*)                            as postings,
            count(*) filter (where is_enriched)  as enriched,
            max(last_seen_at)                    as last_run
        from marts.FT_JOB_POSTING
        """
    ).iloc[0]
    postings = int(row.postings)
    return {
        "postings": postings,
        "enriched": int(row.enriched),
        "coverage": (int(row.enriched) / postings) if postings else 0.0,
        "last_run": row.last_run,
    }


@st.cache_data(ttl=3600, show_spinner=False)
def _seed_facts() -> dict[str, Any]:
    """Sponsor count + refresh date from the committed seed and its sidecar."""
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
def _dbt_facts() -> dict[str, Any]:
    from importlib import import_module

    if _RUN_RESULTS.exists():
        try:
            summarize = import_module("jmi_flows.dbt_status").summarize
            return summarize(json.loads(_RUN_RESULTS.read_text(encoding="utf-8")))
        except (OSError, json.JSONDecodeError, ImportError, KeyError):
            pass
    if _STATUS_FILE.exists():
        try:
            return json.loads(_STATUS_FILE.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            pass
    return {}


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
        facts.append(Fact("postings in warehouse", f"{wh['postings']:,}"))
        facts.append(
            Fact(
                "LLM enrichment coverage",
                f"{wh['coverage']:.0%}",
                "warn" if wh["coverage"] < 0.5 else "good",
                help=(
                    "Share of postings the classifier has read. Coverage is capped by "
                    "the free Gemini quota (~50/day) and accumulates, NL first. The "
                    "remaining postings are **not yet classified** — that is not the "
                    "same as 'no sponsorship'."
                ),
            )
        )
    else:
        facts.append(Fact("warehouse", "unreachable", "bad"))

    seed = _seed_facts()
    if seed.get("sponsors"):
        refreshed = seed.get("refreshed_at")
        label = "recognised sponsors in seed"
        if refreshed:
            label += f" (seed {refreshed})"
        facts.append(
            Fact(
                label,
                f"{int(seed['sponsors']):,}",
                help="The IND register, scraped to a dbt seed. IND republishes it monthly.",
            )
        )

    dbt = _dbt_facts()
    if dbt.get("tests_total"):
        passed, total = int(dbt["tests_passed"]), int(dbt["tests_total"])
        facts.append(
            Fact(
                "dbt tests passing",
                f"{passed}/{total}",
                "good" if passed == total else "bad",
                help="From the last `dbt build`'s `run_results.json` — not a hardcoded count.",
            )
        )
    else:
        facts.append(Fact("dbt tests", "no run recorded", "warn"))

    return facts
