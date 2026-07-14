"""Prefect enrichment flow: classify pending postings with Claude Haiku."""

from __future__ import annotations

import argparse

from prefect import flow

from jmi_core.logging import configure_logging
from jmi_core.settings import get_settings
from jmi_flows.pipeline import enrich_pending


@flow(name="jmi-enrich")
def enrich_flow(limit: int | None = None) -> int:
    settings = get_settings()
    configure_logging(level=settings.log_level, json=settings.log_json)
    return enrich_pending(settings=settings, limit=limit)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the LLM enrichment flow")
    parser.add_argument("--limit", type=int, default=None, help="Max postings to enrich this run")
    args = parser.parse_args()
    enriched = enrich_flow(args.limit)
    print(f"enriched {enriched} postings")


if __name__ == "__main__":
    main()
