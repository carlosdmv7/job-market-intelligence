"""jmi_core — shared contracts for the Job Market Intelligence Engine.

This package is the single source of truth for the canonical schema, imported
by scrapers, the Prefect ingestion flows, the enrichment pipeline, and the app.
The DuckDB DDL in ``warehouse/ddl/`` mirrors these models by hand; keep them in
lockstep and bump SCHEMA_VERSION on any breaking change to either side.
"""

from __future__ import annotations

# Semantic version of the canonical contract. Bump on any field rename/removal,
# enum member change, or content_hash recipe change. Written into every row.
# 0.2.0: added free public-API sources (remotive/arbeitnow/remoteok/adzuna).
SCHEMA_VERSION = "0.2.0"

__all__ = ["SCHEMA_VERSION"]
