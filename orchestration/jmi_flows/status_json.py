"""Publish the latest ``meta.pipeline_run`` row as a static ``status.json``.

The portfolio site shows a "live pipeline state" strip per project. It is a
static page, so it cannot query MotherDuck; it needs a file it can fetch. The
obvious place to put that file is next to the dbt docs this repo already
publishes to GitHub Pages, which costs no extra infrastructure and — unlike the
committed-file design this repo deliberately abandoned (see ``dbt_status``) —
adds no commits to ``main``.

Written into the Pages artifact by ``.github/workflows/dbt-docs.yml`` and
served at ``https://carlosdmv7.github.io/job-market-intelligence/status.json``.
The schema is the portfolio's, documented in its ``docs/freshness-contract.md``.

Best-effort by design: the docs deploy must not fail because the warehouse was
unreachable or the token was missing. Without a readable row this writes
nothing and exits 0, and the portfolio keeps showing its verified snapshot,
which is the fallback that strip was built around.
"""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from jmi_core.logging import get_logger
from jmi_core.warehouse import Warehouse

log = get_logger(__name__)

PROJECT = "job-market-intelligence"

# The newest run wins, and `recorded_at` is written on every run including the
# failed ones — so a red pipeline surfaces as red rather than as stale green.
_LATEST_RUN = """
    select conclusion, tests_passed, tests_total,
           rows_in_warehouse, last_ingest_at, recorded_at
    from meta.pipeline_run
    order by recorded_at desc
    limit 1
"""


def _iso(value: Any) -> str | None:
    """Timestamps go out as UTC ISO 8601; the strip renders them relative."""
    if value is None:
        return None
    if isinstance(value, datetime):
        dt = value.astimezone(UTC) if value.tzinfo else value.replace(tzinfo=UTC)
        return dt.isoformat().replace("+00:00", "Z")
    return str(value)


def build_status() -> dict[str, Any] | None:
    with Warehouse(read_only=True) as wh:
        rows = wh.query(_LATEST_RUN)
    if not rows:
        log.warning("status_json.no_runs_recorded")
        return None

    r = rows[0]
    return {
        "project": PROJECT,
        "generated_at": _iso(r["recorded_at"]),
        "last_ingest_at": _iso(r["last_ingest_at"]),
        "rows_in_warehouse": int(r["rows_in_warehouse"])
        if r["rows_in_warehouse"] is not None
        else None,
        "dbt_tests_passed": int(r["tests_passed"]) if r["tests_passed"] is not None else None,
        "dbt_tests_total": int(r["tests_total"]) if r["tests_total"] is not None else None,
        "last_run_conclusion": r["conclusion"],
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", type=Path, required=True, help="path to write status.json to")
    args = ap.parse_args()

    try:
        status = build_status()
    except Exception as exc:
        log.warning("status_json.unavailable", error=str(exc))
        return 0

    if status is None:
        return 0

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(status, indent=2) + "\n", encoding="utf-8")
    log.info("status_json.written", path=str(args.out), conclusion=status["last_run_conclusion"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
