"""Shared reading of dbt's ``target/`` artifacts.

Two modules distil the same ``run_results.json``: ``dbt_status`` writes the
app's internal freshness feed, ``publish_status`` writes the public summary.
They had each grown their own copy of "which statuses count as a failure" and
"which nodes are tests", which is exactly the pair you want defined once — a
new dbt failure status silently skewing one file and not the other is a bug
nobody would go looking for.
"""

from __future__ import annotations

from typing import Any

#: dbt result statuses that mean "this node did not do its job".
FAILING_STATUSES = frozenset({"error", "fail", "runtime error"})


def is_test(result: dict[str, Any]) -> bool:
    """dbt tags every node; the unique_id prefix is the reliable discriminator."""
    return str(result.get("unique_id", "")).startswith("test.")


def passed(results: list[dict[str, Any]]) -> int:
    """How many of these nodes did their job."""
    return sum(1 for r in results if str(r.get("status", "")).lower() not in FAILING_STATUSES)


def tests(run_results: dict[str, Any]) -> list[dict[str, Any]]:
    """Just the data-test nodes of a run."""
    return [r for r in (run_results.get("results") or []) if is_test(r)]
