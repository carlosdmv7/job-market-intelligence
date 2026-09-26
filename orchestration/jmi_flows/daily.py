"""The daily pipeline as one Prefect flow: ingest → enrich → dbt build → record.

This is what the ``jmi-daily`` deployment runs. It used to be five GitHub
Actions steps calling two thin flows, with ``|| true`` after every source so one
flaky board could not cost the day — which also meant a failed source was a
line in a log nobody reads. Here each source is a task with its own retries and
its own state, the LLM pass has a hard timeout, and dbt is a task whose failure
fails the run. A source that fails after its retries is visible in the run's
graph and does not stop the others; a dbt failure is a failed run.

Where it runs: ``gha_runner.py`` serves it as the ``jmi-daily/daily``
deployment — Prefect Cloud holds the schedule and the history, an hourly
GitHub Actions job is the machine.

Run it directly (no deployment)::

    uv run python -m jmi_flows.daily
    uv run python -m jmi_flows.daily --sources ats jobtech --no-enrich
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

from prefect import flow, get_run_logger, task
from prefect.runtime import flow_run

from jmi_core.logging import configure_logging
from jmi_core.settings import get_settings
from jmi_flows.dbt_status import DEFAULT_RUN_RESULTS, record, summarize
from jmi_flows.pipeline import enrich_pending, ingest_source

REPO_ROOT = Path(__file__).resolve().parents[2]
DBT_DIR = REPO_ROOT / "dbt" / "jmi"

#: Every source the daily run reads, in order: (scraper, country). Adzuna is
#: one scraper swept once per market; the rest are single calls.
SOURCES: tuple[tuple[str, str | None], ...] = (
    ("adzuna", "nl"),
    ("adzuna", "de"),
    ("adzuna", "es"),
    ("jobtech", None),
    ("ats", None),
    ("remotive", None),
    ("arbeitnow", None),
    ("remoteok", None),
)

#: The Gemini free tier allows 20 requests a day and each request carries 10
#: postings — 200 is the ceiling, not a guess.
ENRICH_LIMIT = 200

#: Prefect Cloud rejects a single log message over 25,000 characters, and a
#: full dbt build prints more than that; the summary is at the end anyway.
_MAX_LOG_CHARS = 20_000


def source_label(source: str, country: str | None) -> str:
    return f"{source}-{country}" if country else source


@task(retries=2, retry_delay_seconds=[30, 120], task_run_name="ingest-{label}")
def ingest(source: str, country: str | None, label: str) -> int:
    return ingest_source(source, country=country, run_id=str(flow_run.get_id() or "local"))


@task(timeout_seconds=20 * 60, task_run_name="enrich")
def enrich(limit: int) -> int:
    # Best-effort by design: the classifier opens a circuit breaker after five
    # consecutive provider failures (an exhausted daily quota), and the timeout
    # keeps a slow provider from starving the dbt build of its time.
    return enrich_pending(limit=limit)


def _tail(text: str) -> str:
    if len(text) <= _MAX_LOG_CHARS:
        return text
    return (
        f"[… {len(text) - _MAX_LOG_CHARS:,} earlier characters omitted …]\n{text[-_MAX_LOG_CHARS:]}"
    )


@task(retries=1, retry_delay_seconds=60, task_run_name="dbt-build")
def dbt_build() -> dict[str, Any]:
    logger = get_run_logger()
    dbt = str(Path(sys.executable).parent / "dbt")
    for args in (["deps"], ["build"]):
        result = subprocess.run(
            [dbt, *args], cwd=DBT_DIR, env=os.environ.copy(), capture_output=True, text=True
        )
        logger.info("$ dbt %s\n%s", " ".join(args), _tail(result.stdout))
        if result.returncode != 0:
            logger.error(_tail(result.stderr))
            raise RuntimeError(f"dbt {' '.join(args)} failed (exit {result.returncode})")
    return summarize(json.loads(DEFAULT_RUN_RESULTS.read_text(encoding="utf-8")))


@task(task_run_name="record-run")
def record_run(summary: dict[str, Any], run_conclusion: str) -> dict[str, Any]:
    return record(summary, conclusion=run_conclusion, run_id=str(flow_run.get_id() or "local"))


@flow(name="jmi-daily", log_prints=True)
def daily(
    sources: list[str] | None = None,
    enrich_postings: bool = True,
    enrich_limit: int = ENRICH_LIMIT,
    build: bool = True,
) -> str:
    """Ingest every source, read what's new with the LLM, rebuild the marts.

    ``sources`` narrows the run to some scrapers (``["ats", "jobtech"]``);
    ``enrich_postings`` and ``build`` switch off the LLM pass and dbt — for a
    manual run that must not spend the day's quota or touch the marts.
    """
    settings = get_settings()
    configure_logging(level=settings.log_level, json=settings.log_json)
    logger = get_run_logger()

    failed: list[str] = []
    for source, country in SOURCES:
        if sources and source not in sources:
            continue
        label = source_label(source, country)
        state = ingest(source, country, label, return_state=True)
        if state.is_failed():
            failed.append(label)
    if failed:
        logger.warning("Sources that failed after their retries: %s", ", ".join(failed))

    if enrich_postings:
        state = enrich(enrich_limit, return_state=True)
        if state.is_failed():
            logger.warning("Enrichment failed; continuing to dbt with what is already read.")

    if not build:
        return "success"

    # Recorded whether dbt passed or not: a log that only records successes
    # cannot tell you the pipeline stopped.
    build_state = dbt_build(return_state=True)
    dbt_ok = build_state.is_completed()
    summary = build_state.result() if dbt_ok else {}
    # A source that failed is a partial day, not a failed one: the others landed
    # and the marts were rebuilt from them. dbt failing is a failed day.
    run_conclusion = "success" if dbt_ok else "failure"
    record_run(summary, run_conclusion)
    if not dbt_ok:
        raise RuntimeError("dbt build failed — the marts were not rebuilt")
    return run_conclusion


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the daily pipeline once, locally")
    parser.add_argument("--sources", nargs="*", default=None)
    parser.add_argument("--no-enrich", action="store_true")
    parser.add_argument("--no-build", action="store_true")
    args = parser.parse_args()
    daily(sources=args.sources, enrich_postings=not args.no_enrich, build=not args.no_build)


if __name__ == "__main__":
    main()
