"""Freeze a small, self-contained slice of the warehouse for demo mode.

The app is the project's shop window, and until now cloning the repo and
running it got you six pages of "can't reach the warehouse" unless you had a
MotherDuck token. That is the wrong first impression for the one artefact a
reader is most likely to try.

This writes zstd parquet files holding a sample of the marts, which the app
falls back to when no warehouse is reachable. They are committed, so
``make app`` works on a fresh clone with no secrets and no network.

Parquet rather than a DuckDB file because the same sample is ~360 KB
compressed and ~2.3 MB as a database — and a parquet file diffs as one
opaque blob either way, so the smaller one wins.

Deliberately a *sample*, not a dump:

* it has to stay small enough to live in git (the pre-commit hook caps files
  at 512 KB, and a repo is not a data warehouse);
* the demo needs to be representative, not complete — every chart, filter and
  join in the app must have something real to show.

Referential integrity is preserved: the dimensions are filtered to the keys
the sampled facts actually reference, so the app's joins behave exactly as
they do against MotherDuck.

    uv run python -m jmi_flows.export_demo
"""

from __future__ import annotations

import argparse
from pathlib import Path

from jmi_core.logging import get_logger
from jmi_core.settings import get_settings
from jmi_core.warehouse import Warehouse

log = get_logger(__name__)

_REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUT = _REPO_ROOT / "app" / "demo"

#: Enough postings for every filter in the app to land on something, small
#: enough to commit. Reservoir sampling with a fixed seed so re-exports are
#: comparable rather than a fresh random churn in the diff.
DEFAULT_POSTINGS = 2000
SAMPLE_SEED = 42

#: The sample is **stratified**, not uniform. A flat draw over the whole corpus
#: gave the demo 130 open data roles out of 2,000 rows — because open data roles
#: are ~7% of the warehouse — so the page every visitor lands on looked empty
#: while the parquet was full. The default view gets priority; the remainder is
#: filled with everything else so the history charts and the "show all" toggles
#: still have something behind them.
LIVE_SHARE = 0.6

#: Trends charts need history, but not all of it — and the file has to stay
#: under the 512 KB pre-commit cap, which a full history breaches once the
#: fact sample is weighted toward live postings (they have the most snapshots).
SNAPSHOT_DAYS = 30


def export(out: Path, *, postings: int = DEFAULT_POSTINGS) -> dict[str, int]:
    """Write one parquet per table into ``out``. Returns the row counts."""
    settings = get_settings()
    out.mkdir(parents=True, exist_ok=True)

    counts: dict[str, int] = {}
    with Warehouse(settings.duckdb_database, motherduck_token=settings.motherduck_token) as source:
        # The fact table first: every other table is filtered to what it needs,
        # so the app's joins behave exactly as they do against MotherDuck.
        live_budget = int(postings * LIVE_SHARE)
        counts["FT_JOB_POSTING"] = _write(
            source,
            out / "FT_JOB_POSTING.parquet",
            f"""
            select * from (
                select * from marts.FT_JOB_POSTING where is_target_role and is_active
            ) using sample {live_budget} rows (reservoir, {SAMPLE_SEED})
            union all
            select * from (
                select * from marts.FT_JOB_POSTING where not (is_target_role and is_active)
            ) using sample {postings - live_budget} rows (reservoir, {SAMPLE_SEED})
            """,
        )
        # Everything below filters against the sample that was just written, so
        # read it back as a view rather than re-sampling (which would draw a
        # different set and break the joins).
        source.conn.execute(
            "create or replace temp view sampled as "
            f"select * from read_parquet('{out / 'FT_JOB_POSTING.parquet'}')"
        )

        # Dimensions, narrowed to the keys the sample actually references.
        counts["DT_COMPANY"] = _write(
            source,
            out / "DT_COMPANY.parquet",
            "select * from marts.DT_COMPANY where company_key in "
            "(select distinct company_key from sampled)",
        )
        counts["DT_SOURCE"] = _write(
            source, out / "DT_SOURCE.parquet", "select * from marts.DT_SOURCE"
        )
        counts["DT_DATE"] = _write(source, out / "DT_DATE.parquet", "select * from marts.DT_DATE")

        # Trends need history. Restricted to the sampled postings so the
        # snapshots stay consistent with the facts rather than describing rows
        # the demo does not contain.
        counts["FT_JOB_SNAPSHOT_DAILY"] = _write(
            source,
            out / "FT_JOB_SNAPSHOT_DAILY.parquet",
            "select * from marts.FT_JOB_SNAPSHOT_DAILY where content_hash in "
            "(select distinct content_hash from sampled) "
            f"and date_key >= current_date - {SNAPSHOT_DAYS}",
        )
        counts["pipeline_run"] = _write(
            source,
            out / "pipeline_run.parquet",
            "select * from meta.pipeline_run order by recorded_at desc limit 30",
        )
    return counts


def _write(source: Warehouse, path: Path, sql: str) -> int:
    """Run ``sql`` and write the result as zstd parquet. 0 rows if it fails."""
    try:
        source.conn.execute(f"copy ({sql}) to '{path}' (format parquet, compression zstd)")
    except Exception as exc:
        log.warning("export_demo.table.skipped", path=path.name, error=str(exc))
        return 0
    row = source.conn.execute(f"select count(*) from read_parquet('{path}')").fetchone()
    return int(row[0]) if row else 0


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--postings", type=int, default=DEFAULT_POSTINGS)
    args = parser.parse_args()

    counts = export(args.out, postings=args.postings)
    total_kb = 0.0
    for table, n in counts.items():
        kb = (args.out / f"{table}.parquet").stat().st_size / 1024
        total_kb += kb
        print(f"  {table:<26}{n:>8,} rows{kb:>9,.0f} KB")
    print(f"\n{args.out} — {total_kb:,.0f} KB total")


if __name__ == "__main__":
    main()
