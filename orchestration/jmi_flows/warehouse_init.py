"""One-shot: create the raw/staging/marts schemas and raw tables.

    python -m jmi_flows.warehouse_init
"""

from __future__ import annotations

from jmi_core.logging import configure_logging, get_logger
from jmi_core.settings import get_settings
from jmi_core.warehouse import Warehouse

log = get_logger(__name__)


def main() -> None:
    settings = get_settings()
    configure_logging(level=settings.log_level, json=settings.log_json)
    with Warehouse(
        settings.duckdb_database, motherduck_token=settings.motherduck_token
    ) as wh:
        wh.init_schema()
    log.info("warehouse.init.done", database=settings.duckdb_database)
    print(f"initialized schemas in {settings.duckdb_database}")


if __name__ == "__main__":
    main()
