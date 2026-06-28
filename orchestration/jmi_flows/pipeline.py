"""Pure pipeline logic (no Prefect).

Keeping the work in plain functions means it's unit-testable without a Prefect
runtime; the @flow wrappers in ``ingest.py`` / ``enrich.py`` are thin shells
around these.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Any

from jmi_core.logging import get_logger
from jmi_core.settings import Settings, get_settings
from jmi_core.warehouse import Warehouse

if TYPE_CHECKING:
    from jmi_scrapers.base import BaseScraper

log = get_logger(__name__)


def ingest_source(
    source: str,
    *,
    settings: Settings | None = None,
    warehouse: Warehouse | None = None,
    scraper: BaseScraper | None = None,
    limit: int | None = None,
    run_id: str | None = None,
) -> int:
    """Scrape one source and append observations to raw.raw_job_postings.

    Dependencies are injectable so the flow can be tested with a fake scraper
    and a local DuckDB warehouse.
    """
    settings = settings or get_settings()
    limit = limit or settings.scrape_max_postings
    run_id = run_id or str(uuid.uuid4())

    if scraper is None:
        from jmi_scrapers.registry import get_scraper

        scraper = get_scraper(source, settings, run_id=run_id)

    owns_wh = warehouse is None
    wh = warehouse or Warehouse(
        settings.duckdb_database, motherduck_token=settings.motherduck_token
    )
    try:
        postings = list(scraper.scrape(limit))
        inserted = wh.insert_postings(postings)
        log.info("ingest.done", source=source, scraped=len(postings), inserted=inserted, run_id=run_id)
        return inserted
    finally:
        if owns_wh:
            wh.close()


def enrich_pending(
    *,
    settings: Settings | None = None,
    warehouse: Warehouse | None = None,
    classifier: Any | None = None,
    limit: int | None = None,
) -> int:
    """Classify postings that have no enrichment yet and upsert the results."""
    settings = settings or get_settings()
    limit = limit or settings.enrichment_batch_size

    if classifier is None:
        from jmi_enrichment.classifier import JobClassifier

        classifier = JobClassifier(settings)

    owns_wh = warehouse is None
    wh = warehouse or Warehouse(
        settings.duckdb_database, motherduck_token=settings.motherduck_token
    )
    try:
        pending = wh.fetch_postings_needing_enrichment(limit)
        if not pending:
            log.info("enrich.nothing_pending")
            return 0
        enrichments = list(classifier.classify_many(pending))
        upserted = wh.upsert_enrichments(enrichments)
        log.info("enrich.done", pending=len(pending), enriched=upserted)
        return upserted
    finally:
        if owns_wh:
            wh.close()
