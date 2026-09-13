"""Record how the pipeline run went, into ``meta.pipeline_run``.

The app's freshness header states how many dbt data tests passed, and that
number has to come from a real run rather than a constant somebody forgets to
update. ``dbt/jmi/target/`` is a build artifact and is gitignored, so a
*deployed* app can never read ``run_results.json`` directly.

The previous answer was to distil it into a committed JSON file, which meant
the pipeline pushed a commit to ``main`` every single day — two, in fact — and
a month of that buried the human history under 58 bot commits.

So the run summary goes where every other number the app shows already lives:
the warehouse. One append-only row per run, written at the end of the pipeline
including on failure, because a log that only records successes cannot tell you
the pipeline stopped. The history is then queryable:

    select recorded_at, conclusion, tests_passed, tests_total
    from meta.pipeline_run order by recorded_at desc limit 30;
"""

from __future__ import annotations

import argparse
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from jmi_core.logging import get_logger
from jmi_core.settings import get_settings
from jmi_core.warehouse import Warehouse
from jmi_flows.dbt_artifacts import is_test, passed

log = get_logger(__name__)

_REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_RUN_RESULTS = _REPO_ROOT / "dbt" / "jmi" / "target" / "run_results.json"

_COLUMNS = (
    "run_id",
    "run_started_at",
    "recorded_at",
    "conclusion",
    "dbt_version",
    "tests_total",
    "tests_passed",
    "models_total",
    "models_passed",
    "elapsed_seconds",
    "rows_in_warehouse",
    "last_ingest_at",
)


def summarize(run_results: dict[str, Any]) -> dict[str, Any]:
    """Reduce a dbt run to the handful of numbers the app displays."""
    results = run_results.get("results") or []
    test_nodes = [r for r in results if is_test(r)]
    model_nodes = [r for r in results if not is_test(r)]

    return {
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "run_started_at": (run_results.get("metadata") or {}).get("generated_at"),
        "dbt_version": (run_results.get("metadata") or {}).get("dbt_version"),
        "tests_total": len(test_nodes),
        "tests_passed": passed(test_nodes),
        "models_total": len(model_nodes),
        "models_passed": passed(model_nodes),
        "elapsed_seconds": round(float(run_results.get("elapsed_time") or 0.0), 1),
    }


def warehouse_facts(wh: Warehouse) -> tuple[int | None, Any]:
    """``(row count, newest ingest timestamp)`` for ``marts.FT_JOB_POSTING``.

    ``last_seen_at`` *is* the ingest timestamp: it carries the ``scraped_at`` of
    the newest observation of each posting. Degrades to ``(None, None)`` — a run
    that died before dbt built the marts must still be recorded.
    """
    try:
        row = wh.query(
            "select count(*) as n, max(last_seen_at) as last_ingest_at from marts.FT_JOB_POSTING"
        )[0]
    except Exception as exc:
        log.warning("dbt_status.marts.unavailable", error=str(exc))
        return None, None
    return int(row["n"]), row["last_ingest_at"]


def record(summary: dict[str, Any], *, conclusion: str, run_id: str) -> dict[str, Any]:
    """Append one row to ``meta.pipeline_run`` and return what was written."""
    settings = get_settings()
    with Warehouse(settings.duckdb_database, motherduck_token=settings.motherduck_token) as wh:
        wh.init_schema()  # idempotent; creates meta.pipeline_run on first run
        rows, last_ingest_at = warehouse_facts(wh)
        values = {
            "run_id": run_id,
            "run_started_at": summary.get("run_started_at"),
            "recorded_at": datetime.now(UTC),
            "conclusion": conclusion,
            "dbt_version": summary.get("dbt_version"),
            "tests_total": summary.get("tests_total"),
            "tests_passed": summary.get("tests_passed"),
            "models_total": summary.get("models_total"),
            "models_passed": summary.get("models_passed"),
            "elapsed_seconds": summary.get("elapsed_seconds"),
            "rows_in_warehouse": rows,
            "last_ingest_at": last_ingest_at,
        }
        placeholders = ", ".join("?" for _ in _COLUMNS)
        wh.execute(
            f"insert into meta.pipeline_run ({', '.join(_COLUMNS)}) values ({placeholders})",
            [values[c] for c in _COLUMNS],
        )
    return values


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-results", type=Path, default=DEFAULT_RUN_RESULTS)
    parser.add_argument(
        "--conclusion",
        default=os.environ.get("JMI_RUN_CONCLUSION", "unknown"),
        help="Outcome of the run (GitHub Actions passes job.status).",
    )
    parser.add_argument(
        "--run-id",
        default=os.environ.get("GITHUB_RUN_ID", "local"),
        help="Identifier for this run; the GitHub Actions run id in CI.",
    )
    args = parser.parse_args()

    # A run that died before dbt finished still gets a row — with nulls where
    # dbt never produced numbers. That absence is the signal.
    summary: dict[str, Any] = {}
    if args.run_results.exists():
        summary = summarize(json.loads(args.run_results.read_text(encoding="utf-8")))
    else:
        log.warning("dbt_status.run_results.missing", path=str(args.run_results))

    written = record(summary, conclusion=args.conclusion, run_id=args.run_id)
    print(
        f"recorded run {written['run_id']} ({written['conclusion']}): "
        f"{written['tests_passed']}/{written['tests_total']} tests, "
        f"{written['rows_in_warehouse']} rows -> meta.pipeline_run"
    )


if __name__ == "__main__":
    main()
