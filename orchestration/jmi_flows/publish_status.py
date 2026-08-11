"""Publish a one-file public status summary to ``docs/status.json``.

Who reads this: anything outside the warehouse — a README badge, a monitor, a
recruiter clicking through the repo. It answers "is this project alive, and how
much is in it?" without a MotherDuck token.

It is deliberately written at the *end* of the daily pipeline with
``if: always()``, so it also records the runs that failed. That is the whole
point: a status file that only appears on green days cannot tell you the
pipeline stopped. Every lookup here degrades to ``None`` rather than raising —
a broken warehouse must still produce a status file saying so.

Distinct from ``jmi_flows.dbt_status`` / ``docs/status/pipeline.json``, which is
the *app's* internal freshness feed (dbt run detail). This one is the external
summary and is keyed to the schema below.
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
from jmi_flows.dbt_artifacts import passed, tests

log = get_logger(__name__)

_REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_MANIFEST = _REPO_ROOT / "dbt" / "jmi" / "target" / "manifest.json"
DEFAULT_RUN_RESULTS = _REPO_ROOT / "dbt" / "jmi" / "target" / "run_results.json"
DEFAULT_OUT = _REPO_ROOT / "docs" / "status.json"

PROJECT = "job-market-intelligence"


def warehouse_facts() -> tuple[int | None, str | None]:
    """``(row count, newest ingest timestamp)`` for ``marts.FT_JOB_POSTING``.

    ``last_seen_at`` *is* the ingest timestamp: it carries the ``scraped_at`` of
    the newest observation of each posting, so its max is when the warehouse
    last took data in.
    """
    settings = get_settings()
    with Warehouse(settings.duckdb_database, motherduck_token=settings.motherduck_token) as wh:
        row = wh.query(
            "select count(*) as rows_in_warehouse, max(last_seen_at) as last_ingest_at "
            "from marts.FT_JOB_POSTING"
        )[0]
    last = row["last_ingest_at"]
    return int(row["rows_in_warehouse"]), (_isoformat(last) if last is not None else None)


def _isoformat(value: Any) -> str:
    """dbt/DuckDB hand back naive datetimes; publish them as explicit UTC."""
    if isinstance(value, datetime):
        moment = value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
        return moment.isoformat(timespec="seconds")
    return str(value)


def count_manifest_tests(manifest_path: Path) -> int | None:
    """How many data tests the dbt project *defines* (not how many ran).

    The manifest is the project's own declaration, so this number stays honest
    even when the build died before reaching the tests.
    """
    if not manifest_path.exists():
        return None
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    nodes: dict[str, Any] = manifest.get("nodes") or {}
    return sum(1 for node in nodes.values() if node.get("resource_type") == "test")


def count_passed_tests(run_results_path: Path) -> int | None:
    """How many data tests actually passed in the run that just happened."""
    if not run_results_path.exists():
        return None
    run_results = json.loads(run_results_path.read_text(encoding="utf-8"))
    return passed(tests(run_results))


def build_status(
    *,
    conclusion: str,
    manifest_path: Path = DEFAULT_MANIFEST,
    run_results_path: Path = DEFAULT_RUN_RESULTS,
) -> dict[str, Any]:
    try:
        rows, last_ingest_at = warehouse_facts()
    except Exception as exc:  # unreachable warehouse, missing marts, bad token
        log.warning("publish_status.warehouse.unavailable", error=str(exc))
        rows, last_ingest_at = None, None

    return {
        "project": PROJECT,
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "last_ingest_at": last_ingest_at,
        "rows_in_warehouse": rows,
        "dbt_tests_passed": count_passed_tests(run_results_path),
        "dbt_tests_total": count_manifest_tests(manifest_path),
        "last_run_conclusion": conclusion,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Write docs/status.json.")
    parser.add_argument(
        "--conclusion",
        default=os.environ.get("JMI_RUN_CONCLUSION", "unknown"),
        help="Outcome of the pipeline run (GitHub Actions passes job.status).",
    )
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--run-results", type=Path, default=DEFAULT_RUN_RESULTS)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args()

    status = build_status(
        conclusion=args.conclusion,
        manifest_path=args.manifest,
        run_results_path=args.run_results,
    )

    # `generated_at` moves every run, so writing unconditionally would hand the
    # workflow a diff every single day and bury the history this file exists to
    # provide. Only rewrite when something you would actually want to read
    # changed.
    if args.out.exists() and not _substantive_change(args.out, status):
        print(f"status unchanged -> left {args.out} alone")
        return

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(status, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(status, indent=2))


def _substantive_change(path: Path, status: dict[str, Any]) -> bool:
    """Has anything other than the clock changed since the last publish?"""
    try:
        previous = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return True  # unreadable or corrupt: replace it
    return {k: v for k, v in previous.items() if k != "generated_at"} != {
        k: v for k, v in status.items() if k != "generated_at"
    }


if __name__ == "__main__":
    main()
