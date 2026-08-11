"""A provider that replays recorded model output instead of calling anything.

This is what makes the CI eval job possible: no API key, no quota, no network,
and — the part that matters — no variance. A red eval in CI means *the code or
the prompt changed*, never "the model had a bad morning".

The recordings are real production outputs, lifted from ``raw.raw_job_enrichment``
where the pipeline already stored every validated response. Recording therefore
costs nothing extra and the fixtures cannot drift from what the system actually
produced.
"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import TYPE_CHECKING, TypeVar

from pydantic import BaseModel

from jmi_enrichment.providers import ClassificationError, LLMUsage
from jmi_evals.dataset import (
    RESPONSES_PATH,
    RecordedResponse,
    load_golden_set,
    load_responses,
    save_responses,
)

if TYPE_CHECKING:
    from jmi_evals.dataset import GoldenRecord

T = TypeVar("T", bound=BaseModel)


class MissingRecording(ClassificationError):
    """No fixture for this posting — re-record rather than silently skipping."""


class ReplayProvider:
    """Implements the ``LLMProvider`` protocol against a fixture file.

    Lookup is by ``content_hash``, which the classifier does not pass down, so
    the caller sets :attr:`current` before each ``classify`` call. That is a
    little awkward and deliberately so: the alternative — matching on the
    prompt text — would silently return a stale answer whenever the prompt
    changed, which is exactly the regression the evals exist to catch.
    """

    def __init__(self, recordings: dict[str, RecordedResponse], *, model: str = "replay"):
        self.recordings = recordings
        self.model = model
        self.current: str | None = None

    def classify(self, *, system: str, user: str, schema: type[T]) -> tuple[T, LLMUsage]:
        if self.current is None:
            raise MissingRecording("ReplayProvider.current was not set before classify()")
        rec = self.recordings.get(self.current)
        if rec is None:
            raise MissingRecording(
                f"no recorded response for {self.current[:12]} — run "
                "`uv run python -m jmi_evals.replay --record`"
            )
        return schema.model_validate(rec.response), LLMUsage(0, 0, 0.0)

    def complete(self, *, system: str, user: str) -> str:
        raise NotImplementedError("ReplayProvider only replays classifications")


def record_from_warehouse(
    records: list[GoldenRecord], *, path: Path = RESPONSES_PATH
) -> list[RecordedResponse]:
    """Harvest the stored ``raw_response`` for every golden-set posting.

    Rows the pipeline has not enriched yet simply have no recording; they are
    reported and skipped, and the CI subset is whatever *is* recorded.
    """
    from jmi_core.settings import get_settings
    from jmi_core.warehouse import Warehouse

    settings = get_settings()
    wh = Warehouse(
        settings.duckdb_database, read_only=True, motherduck_token=settings.motherduck_token
    )
    by_hash = {r.content_hash: r for r in records}
    if not by_hash:
        return []

    placeholders = ", ".join("?" for _ in by_hash)
    rows = wh.conn.execute(
        f"""
        select content_hash, model, prompt_version, raw_response
        from raw.raw_job_enrichment
        where content_hash in ({placeholders}) and raw_response is not null
        """,
        list(by_hash),
    ).df()

    import json as _json

    out: list[RecordedResponse] = []
    for row in rows.to_dict("records"):
        payload = row["raw_response"]
        if isinstance(payload, str):
            payload = _json.loads(payload)
        golden = by_hash[row["content_hash"]]
        out.append(
            RecordedResponse(
                content_hash=row["content_hash"],
                text_sha256=golden.text_sha256,
                model=row["model"],
                prompt_version=row["prompt_version"],
                response=payload,
            )
        )
    return sorted(out, key=lambda r: r.content_hash)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--record",
        action="store_true",
        help="harvest recorded responses for the golden set from the warehouse",
    )
    parser.add_argument("--out", type=Path, default=RESPONSES_PATH)
    args = parser.parse_args()

    if not args.record:
        cached = load_responses(args.out)
        print(f"{len(cached)} recorded responses at {args.out}")
        return

    golden = load_golden_set()
    recorded = record_from_warehouse(golden, path=args.out)
    save_responses(recorded, args.out)
    missing = len(golden) - len(recorded)
    print(f"recorded {len(recorded)} responses -> {args.out}")
    if missing:
        print(
            f"{missing} golden postings have no enrichment yet — they are excluded "
            "from the CI subset until the daily pipeline reaches them."
        )


if __name__ == "__main__":
    main()
