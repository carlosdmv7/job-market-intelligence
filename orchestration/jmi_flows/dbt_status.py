"""Distil dbt's ``run_results.json`` into a small committed status file.

``dbt/jmi/target/`` is a build artifact and is gitignored, so the *deployed*
Streamlit app can never see it — but the app's freshness header has to state
how many data tests passed, and that number must come from a real run rather
than a constant somebody forgets to update.

The daily pipeline therefore runs this after ``dbt build`` and commits the
result to ``docs/status/pipeline.json``. Small, diffable, and the git history
doubles as a record of when the warehouse last built clean.
"""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from jmi_flows.dbt_artifacts import is_test, passed

_REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_RUN_RESULTS = _REPO_ROOT / "dbt" / "jmi" / "target" / "run_results.json"
DEFAULT_OUT = _REPO_ROOT / "docs" / "status" / "pipeline.json"


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


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-results", type=Path, default=DEFAULT_RUN_RESULTS)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args()

    if not args.run_results.exists():
        raise SystemExit(f"no run_results.json at {args.run_results} — run `dbt build` first")

    summary = summarize(json.loads(args.run_results.read_text(encoding="utf-8")))
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(
        f"{summary['tests_passed']}/{summary['tests_total']} tests passed, "
        f"{summary['models_passed']}/{summary['models_total']} models -> {args.out}"
    )


if __name__ == "__main__":
    main()
