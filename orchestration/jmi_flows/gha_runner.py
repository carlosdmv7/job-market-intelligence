"""Serve the ``jmi-daily`` deployment from a GitHub Actions runner, for one pass.

Prefect Cloud holds the deployment's schedule (05:15 UTC daily), its parameters
and its run history; this module lends it a machine.
``.github/workflows/pipeline.yml`` wakes up hourly and calls it:

1. Register the deployment from the code below — a *served* deployment, so its
   definition is always what is on ``main``, and it needs no work pool.
2. Ask Cloud whether any of its runs is due: the scheduled one, or one started
   by hand from the Prefect UI. None: exit in seconds.
3. Otherwise start a ``Runner`` for a single pass, which executes the due runs
   and waits for them, then read back how each ended. A run that did not
   complete fails the job, so a broken pipeline still turns the Actions tab red
   and sends GitHub's email.

Why a borrowed runner: Prefect Cloud's free tier has no hybrid work pools, and
its serverless compute is 500 minutes a month against ~300 for this pipeline
alone. Actions minutes on a public repository are free.

    uv run python -m jmi_flows.gha_runner
"""

from __future__ import annotations

import asyncio
import os
import sys
from datetime import UTC, datetime, timedelta
from uuid import UUID

from prefect.client.orchestration import get_client
from prefect.client.schemas.objects import StateType
from prefect.runner import Runner

from jmi_flows.daily import daily

DEPLOYMENT = "daily"
SCHEDULE = "15 5 * * *"  # 05:15 UTC
#: The runner prefetches runs due this soon; the check below uses the same window.
PREFETCH = timedelta(seconds=10)


def set_output(**values: str) -> None:
    path = os.environ.get("GITHUB_OUTPUT")
    if path:
        with open(path, "a", encoding="utf-8") as fh:
            fh.writelines(f"{k}={v}\n" for k, v in values.items())


async def serve_once() -> int:
    runner = Runner(
        name=f"github-actions-{os.environ.get('GITHUB_RUN_ID', 'local')}",
        limit=1,  # one pipeline at a time: they write the same warehouse
        prefetch_seconds=PREFETCH.total_seconds(),
    )
    deployment_id: UUID = await runner.aadd_flow(
        daily,
        name=DEPLOYMENT,
        cron=SCHEDULE,
        tags=["job-market-intelligence"],
        description=(
            "Ingest every source (Adzuna NL/DE/ES, JobTech SE, Irish employers' ATS "
            "boards, three remote boards), read new postings with the LLM, rebuild the "
            "marts with dbt, and record the run in meta.pipeline_run. Served from an "
            "hourly GitHub Actions job: a run shows as Late until that job picks it up."
        ),
    )

    async with get_client() as client:
        due = await client.get_scheduled_flow_runs_for_deployments(
            [deployment_id], scheduled_before=datetime.now(UTC) + PREFETCH
        )
    if not due:
        print("Nothing due.")
        set_output(ran="false")
        return 0

    ids = [run.id for run in due]
    print(f"{len(ids)} run(s) due: {', '.join(map(str, ids))}")
    await runner.start(run_once=True)

    async with get_client() as client:
        states = {run_id: (await client.read_flow_run(run_id)).state for run_id in ids}
    for run_id, state in states.items():
        print(f"{run_id}: {state.type.value if state else 'no state'}")
    # Still scheduled (more were due than one pass takes): the next hour runs it.
    finished = [s for s in states.values() if s and s.type != StateType.SCHEDULED]
    ok = all(s.type == StateType.COMPLETED for s in finished)
    set_output(ran="true", conclusion="success" if ok else "failure")
    return 0 if ok else 1


def main() -> int:
    return asyncio.run(serve_once())


if __name__ == "__main__":
    sys.exit(main())
