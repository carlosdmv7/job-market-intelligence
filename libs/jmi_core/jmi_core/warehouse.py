"""MotherDuck/DuckDB access layer.

One small class that owns the connection and the write contract for the ``raw``
schema. The ingestion flow inserts :class:`~jmi_core.schema.raw.JobPosting`
rows (append-only event log); the enrichment flow upserts
:class:`~jmi_core.schema.enrichment.JobEnrichment` rows keyed by ``content_hash``.

Connecting to MotherDuck: pass ``database="md:job_market"`` and set the
``motherduck_token`` env var. For local dev/CI pass a filesystem path.
"""

from __future__ import annotations

import json
import os
from contextlib import contextmanager
from pathlib import Path
from typing import TYPE_CHECKING, Any

import duckdb

from jmi_core.schema.enrichment import JobEnrichment
from jmi_core.schema.raw import JobPosting

if TYPE_CHECKING:
    from collections.abc import Iterator, Sequence

# Repo-root/warehouse/ddl — the DDL files mirror the Pydantic models by hand.
_DEFAULT_DDL_DIR = Path(__file__).resolve().parents[3] / "warehouse" / "ddl"

# Column order for raw.raw_job_postings inserts (content_hash is computed).
_POSTING_COLUMNS: tuple[str, ...] = (
    "source",
    "source_job_id",
    "source_url",
    "apply_url",
    "ingestion_run_id",
    "scraped_at",
    "title",
    "company_name",
    "company_url",
    "description_raw",
    "detected_language",
    "location_raw",
    "country_code",
    "is_remote_raw",
    "posted_at",
    "valid_through",
    "salary_raw",
    "employment_type_raw",
    "seniority_raw",
    "raw_payload",
    "content_hash",
    "schema_version",
)

# Column order for raw.raw_job_enrichment upserts (visa flattened to visa_*).
_ENRICHMENT_COLUMNS: tuple[str, ...] = (
    "content_hash",
    "source",
    "source_job_id",
    "enriched_at",
    "model",
    "prompt_version",
    "schema_version",
    "input_tokens",
    "output_tokens",
    "cost_usd",
    "normalized_role",
    "role_family",
    "seniority",
    "employment_type",
    "remote_policy",
    "technologies",
    "visa_status",
    "visa_confidence",
    "visa_evidence",
    "visa_reasoning",
    "requires_local_language",
    "working_languages",
    "english_sufficient",
    "relocation_support",
    "enrichment_confidence",
    "raw_response",
)

_JSON_COLUMNS = {"raw_payload", "raw_response"}


def _enum_value(value: Any) -> Any:
    """Serialize enum members to their string value for DuckDB."""
    return value.value if hasattr(value, "value") else value


class Warehouse:
    """Thin wrapper over a DuckDB connection with typed loaders."""

    def __init__(
        self,
        database: str = "md:job-market-intelligence",
        *,
        read_only: bool = False,
        motherduck_token: str | None = None,
    ) -> None:
        self.database = database
        self._read_only = read_only
        self._motherduck_token = motherduck_token
        self._conn: duckdb.DuckDBPyConnection | None = None

    # --- connection ------------------------------------------------------
    @property
    def conn(self) -> duckdb.DuckDBPyConnection:
        if self._conn is None:
            target = self.database
            if self.database.startswith("md:"):
                target = self._motherduck_target()
            elif self.database not in (":memory:", ""):
                Path(self.database).expanduser().parent.mkdir(parents=True, exist_ok=True)
            self._conn = duckdb.connect(target, read_only=self._read_only)
        return self._conn

    def _motherduck_target(self) -> str:
        """Validate the token and embed it in the connection string.

        Passing it on the connection string (rather than relying on env-var
        propagation) is the most reliable path and avoids a stale shell
        ``motherduck_token`` shadowing the configured one.
        """
        token = (self._motherduck_token or os.environ.get("motherduck_token") or "").strip()
        if not token:
            raise RuntimeError(
                "MotherDuck token missing. Set `motherduck_token=...` in .env "
                "(database is " + self.database + ")."
            )
        if token.count(".") != 2:
            raise RuntimeError(
                "MotherDuck token looks malformed: a valid token is a JWT with exactly 3 "
                f"dot-separated sections, but this one has {token.count('.') + 1}. "
                "Re-copy it from app.motherduck.com as a single line (a line break or stray "
                "quotes/spaces in .env is the usual cause)."
            )
        os.environ["motherduck_token"] = token  # the extension also reads this
        if "motherduck_token=" in self.database:
            return self.database
        sep = "&" if "?" in self.database else "?"
        return f"{self.database}{sep}motherduck_token={token}"

    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    def __enter__(self) -> Warehouse:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # --- schema ----------------------------------------------------------
    def init_schema(self, ddl_dir: Path | None = None) -> None:
        """Execute every ``*.sql`` file under ``ddl_dir`` in filename order."""
        ddl_dir = ddl_dir or _DEFAULT_DDL_DIR
        files = sorted(ddl_dir.rglob("*.sql"))
        if not files:
            raise FileNotFoundError(f"No DDL files found under {ddl_dir}")
        for path in files:
            for statement in _split_sql(path.read_text(encoding="utf-8")):
                self.conn.execute(statement)

    # --- writes ----------------------------------------------------------
    def insert_postings(self, postings: Sequence[JobPosting]) -> int:
        """Append posting observations to raw.raw_job_postings."""
        if not postings:
            return 0
        rows = [self._posting_row(p) for p in postings]
        placeholders = ", ".join("?" for _ in _POSTING_COLUMNS)
        cols = ", ".join(_POSTING_COLUMNS)
        with self._transaction():
            self.conn.executemany(
                f"INSERT INTO raw.raw_job_postings ({cols}) VALUES ({placeholders})", rows
            )
        return len(rows)

    def upsert_enrichments(self, enrichments: Sequence[JobEnrichment]) -> int:
        """Insert-or-replace enrichments keyed by content_hash (PK)."""
        if not enrichments:
            return 0
        rows = [self._enrichment_row(e) for e in enrichments]
        placeholders = ", ".join("?" for _ in _ENRICHMENT_COLUMNS)
        cols = ", ".join(_ENRICHMENT_COLUMNS)
        with self._transaction():
            self.conn.executemany(
                f"INSERT OR REPLACE INTO raw.raw_job_enrichment ({cols}) VALUES ({placeholders})",
                rows,
            )
        return len(rows)

    # --- reads -----------------------------------------------------------
    def fetch_postings_needing_enrichment(self, limit: int = 50) -> list[dict[str, Any]]:
        """Latest content version per posting that has no enrichment row yet."""
        sql = """
        WITH latest AS (
            SELECT DISTINCT ON (content_hash) *
            FROM raw.raw_job_postings
            ORDER BY content_hash, scraped_at DESC
        )
        SELECT l.content_hash, l.source, l.source_job_id, l.title, l.company_name,
               l.location_raw, l.country_code, l.salary_raw, l.description_raw,
               l.detected_language
        FROM latest l
        LEFT JOIN raw.raw_job_enrichment e USING (content_hash)
        WHERE e.content_hash IS NULL
        LIMIT ?
        """
        return self.query(sql, [limit])

    def query(self, sql: str, params: Sequence[Any] | None = None) -> list[dict[str, Any]]:
        """Run a query and return rows as dicts."""
        cur = self.conn.execute(sql, list(params) if params else None)
        cols = [d[0] for d in cur.description] if cur.description else []
        return [dict(zip(cols, row, strict=True)) for row in cur.fetchall()]

    def execute(self, sql: str, params: Sequence[Any] | None = None) -> None:
        self.conn.execute(sql, list(params) if params else None)

    # --- internals -------------------------------------------------------
    @contextmanager
    def _transaction(self) -> Iterator[None]:
        self.conn.execute("BEGIN TRANSACTION")
        try:
            yield
        except Exception:
            self.conn.execute("ROLLBACK")
            raise
        else:
            self.conn.execute("COMMIT")

    @staticmethod
    def _posting_row(p: JobPosting) -> list[Any]:
        data = p.model_dump()
        row: list[Any] = []
        for col in _POSTING_COLUMNS:
            value = data[col]
            if col == "source":
                value = _enum_value(value)
            elif col in _JSON_COLUMNS:
                value = json.dumps(value) if value is not None else None
            row.append(value)
        return row

    @staticmethod
    def _enrichment_row(e: JobEnrichment) -> list[Any]:
        data = e.model_dump()
        visa = data["visa"]
        flat: dict[str, Any] = {
            **data,
            "source": _enum_value(data["source"]),
            "seniority": _enum_value(data["seniority"]),
            "employment_type": _enum_value(data["employment_type"]),
            "remote_policy": _enum_value(data["remote_policy"]),
            "visa_status": _enum_value(visa["status"]),
            "visa_confidence": visa["confidence"],
            "visa_evidence": visa["evidence"],
            "visa_reasoning": visa["reasoning"],
            "raw_response": json.dumps(data["raw_response"])
            if data["raw_response"] is not None
            else None,
        }
        return [flat[col] for col in _ENRICHMENT_COLUMNS]


def _split_sql(script: str) -> list[str]:
    """Split a DDL script into individual statements on the semicolon.

    Strips ``--`` line comments first (they may contain semicolons), then
    splits. Our DDL has no semicolons inside string literals, so this is safe
    and avoids relying on driver-specific multi-statement execution.
    """
    without_comments = "\n".join(line.split("--", 1)[0] for line in script.splitlines())
    return [s.strip() for s in without_comments.split(";") if s.strip()]
