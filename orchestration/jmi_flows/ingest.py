"""Prefect ingestion flow: scrape one source -> raw.raw_job_postings."""

from __future__ import annotations

import argparse

from prefect import flow
from prefect.runtime import flow_run

from jmi_core.logging import configure_logging
from jmi_core.settings import get_settings

from jmi_flows.pipeline import ingest_source


@flow(name="jmi-ingest")
def ingest_flow(source: str = "honeypot", limit: int | None = None) -> int:
    settings = get_settings()
    configure_logging(level=settings.log_level, json=settings.log_json)
    run_id = flow_run.get_id() or None
    return ingest_source(source, settings=settings, limit=limit, run_id=run_id)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the ingestion flow for one source")
    parser.add_argument("--source", default="honeypot")
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args()
    inserted = ingest_flow(args.source, args.limit)
    print(f"inserted {inserted} postings from {args.source}")


if __name__ == "__main__":
    main()
