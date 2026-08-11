"""Draw a stratified sample from the warehouse into a labelling template.

Sampling is the part that decides whether the eval is honest, so it is a script
rather than a one-off query someone ran once and forgot:

* **Stratified**, not random. A uniform sample of this corpus would be ~90%
  ``unclear`` postings from remote boards and would say nothing about the
  classes the product exists for. Strata are (market x register match), and
  within each stratum postings that *look* like they discuss visas are
  over-sampled so the rare classes are actually represented.
* **Deterministic.** Selection is ordered by a hash of ``content_hash`` plus a
  fixed seed, so re-running reproduces the same sample and a grown corpus
  extends the set rather than reshuffling it.
* **Additive.** An existing golden set is read first and its labels are
  preserved; only new rows are appended.

Usage::

    uv run python -m jmi_evals.sample --size 200          # write the template
    uv run python -m jmi_evals.sample --size 200 --dry-run

Then fill in ``visa_status_true`` on each line by hand.
"""

from __future__ import annotations

import argparse
import hashlib
from pathlib import Path
from typing import Any

from jmi_core.logging import get_logger
from jmi_core.settings import get_settings
from jmi_core.warehouse import Warehouse
from jmi_enrichment.prompts import build_user_prompt
from jmi_evals.dataset import (
    GOLDEN_SET_PATH,
    GoldenRecord,
    load_golden_set,
    save_golden_set,
    text_hash,
)

log = get_logger(__name__)

DEFAULT_SEED = "jmi-golden-v1"

#: Cues that a posting probably says something about the right to work. Used
#: only to *over-sample* likely-informative rows — never to label them. The
#: labels come from a human reading the text.
_VISA_CUES = [
    "visa",
    "sponsor",
    "relocation",
    "relocate",
    "work permit",
    "werkvergunning",
    "kennismigrant",
    "highly skilled migrant",
    "right to work",
    "work authorization",
    "work authorisation",
    "eu citizen",
    "permiso de trabajo",
    "arbeitserlaubnis",
]

# staging holds one row per daily *observation*, so it must be collapsed to one
# description per content_hash before joining — otherwise a posting seen on ten
# days would enter the sampling pool ten times and skew every stratum.
_QUERY = """
with descriptions as (
    select content_hash, any_value(description_raw) as description_raw
    from staging.stg_job_postings
    where description_raw is not null and length(description_raw) > 200
    group by content_hash
)
select
    f.content_hash,
    f.title,
    f.company_name,
    f.country_code,
    f.location_raw,
    f.salary_raw,
    f.source,
    f.source_url,
    f.is_recognised_sponsor,
    f.visa_status              as llm_status_at_sampling,
    s.description_raw,
    coalesce(f.country_code, '(remote)') as stratum_market,
    ({cue_expr}) as mentions_visa
from marts.FT_JOB_POSTING f
join descriptions s on s.content_hash = f.content_hash
"""


def _cue_expression() -> str:
    """SQL boolean: does the description mention anything permit-related?"""
    parts = [f"lower(s.description_raw) like '%{cue}%'" for cue in _VISA_CUES]
    return " or ".join(parts)


def _rank(content_hash: str, seed: str) -> str:
    """Deterministic, uniformly-distributed sort key."""
    return hashlib.sha256(f"{seed}:{content_hash}".encode()).hexdigest()


def _clean(value: Any) -> str | None:
    """pandas hands back NaN for SQL NULL, and ``float('nan')`` is *truthy* —
    so an `or None` guard silently lets it through into a typed field."""
    import pandas as pd

    if value is None or (pd.api.types.is_scalar(value) and pd.isna(value)):
        return None
    text = str(value).strip()
    return text or None


def _to_record(row: dict[str, Any]) -> GoldenRecord:
    prompt_input = build_user_prompt(
        {
            "title": _clean(row.get("title")),
            "company_name": _clean(row.get("company_name")),
            "location_raw": _clean(row.get("location_raw")),
            "country_code": _clean(row.get("country_code")),
            "salary_raw": _clean(row.get("salary_raw")),
            "description_raw": _clean(row.get("description_raw")),
        }
    )
    return GoldenRecord(
        content_hash=row["content_hash"],
        text_sha256=text_hash(prompt_input),
        title=_clean(row.get("title")),
        company_name=_clean(row.get("company_name")),
        country_code=_clean(row.get("country_code")),
        source=_clean(row.get("source")),
        source_url=_clean(row.get("source_url")),
        is_recognised_sponsor=bool(row.get("is_recognised_sponsor")),
        llm_status_at_sampling=_clean(row.get("llm_status_at_sampling")),
        visa_status_true=None,
        notes="",
        prompt_input=prompt_input,
    )


def _stratum(row: dict[str, Any]) -> tuple[str, bool]:
    return (str(row["stratum_market"]), bool(row["is_recognised_sponsor"]))


def _spread(rows: list[dict[str, Any]], n: int, seed: str) -> list[dict[str, Any]]:
    """Take ``n`` rows as evenly across strata as the strata allow.

    Round-robin rather than fixed quotas: when a stratum runs out (DE has only
    ten recognised sponsors in the whole corpus) its unused share flows to the
    others instead of silently shrinking the sample.
    """
    if n <= 0:
        return []
    strata: dict[tuple[str, bool], list[dict[str, Any]]] = {}
    for row in rows:
        strata.setdefault(_stratum(row), []).append(row)
    for members in strata.values():
        members.sort(key=lambda r: _rank(r["content_hash"], seed))

    picked: list[dict[str, Any]] = []
    keys = sorted(strata)
    cursors = dict.fromkeys(keys, 0)
    while len(picked) < n:
        progressed = False
        for key in keys:
            if len(picked) >= n:
                break
            i = cursors[key]
            if i < len(strata[key]):
                picked.append(strata[key][i])
                cursors[key] = i + 1
                progressed = True
        if not progressed:  # every stratum exhausted
            break
    return picked


def stratified_sample(
    rows: list[dict[str, Any]],
    *,
    size: int,
    seed: str = DEFAULT_SEED,
    exclude: set[str] | None = None,
    cue_share: float = 0.6,
) -> list[dict[str, Any]]:
    """Pick ``size`` rows, over-weighting postings that discuss the right to work.

    Only ~3% of this corpus mentions permits at all, so a proportional sample
    would contain almost no ``explicit_yes``/``explicit_no`` and the evals
    would measure nothing but the ``unclear`` majority. ``cue_share`` of the
    sample is therefore drawn from the cue-matching pool (capped by how many
    exist), and the rest from ordinary postings — which is what keeps the
    classifier's *false positive* rate measurable.

    The over-sampling is a property of the sample, not of the labels: the cue
    list decides what gets read, never what it is worth.
    """
    exclude = exclude or set()
    pool = [r for r in rows if r["content_hash"] not in exclude]
    if not pool:
        return []

    cued = [r for r in pool if r["mentions_visa"]]
    plain = [r for r in pool if not r["mentions_visa"]]

    picked = _spread(cued, min(len(cued), round(size * cue_share)), seed)
    taken = {r["content_hash"] for r in picked}
    picked += _spread(plain, size - len(picked), seed)
    # If the plain pool ran dry first, top up from any cued rows left over.
    if len(picked) < size:
        leftover = [r for r in cued if r["content_hash"] not in taken]
        picked += _spread(leftover, size - len(picked), seed)

    return sorted(picked, key=lambda r: _rank(r["content_hash"], seed))[:size]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--size", type=int, default=200, help="target golden-set size")
    parser.add_argument("--seed", default=DEFAULT_SEED)
    parser.add_argument("--out", type=Path, default=GOLDEN_SET_PATH)
    parser.add_argument(
        "--cue-share",
        type=float,
        default=0.6,
        help="fraction of each stratum reserved for permit-mentioning postings",
    )
    parser.add_argument("--dry-run", action="store_true", help="report strata, write nothing")
    args = parser.parse_args()

    existing = load_golden_set(args.out) if args.out.exists() else []
    labelled = sum(1 for r in existing if r.is_labelled)
    print(f"existing golden set: {len(existing)} rows ({labelled} labelled)")

    settings = get_settings()
    wh = Warehouse(
        settings.duckdb_database, read_only=True, motherduck_token=settings.motherduck_token
    )
    rows = wh.conn.execute(_QUERY.format(cue_expr=_cue_expression())).df().to_dict("records")
    print(f"candidate postings with a usable description: {len(rows):,}")

    need = max(args.size - len(existing), 0)
    if not need:
        print(f"already at {len(existing)} rows — nothing to sample.")
        return

    picked = stratified_sample(
        rows,
        size=need,
        seed=args.seed,
        exclude={r.content_hash for r in existing},
        cue_share=args.cue_share,
    )

    by_stratum: dict[str, int] = {}
    for row in picked:
        key = f"{row['stratum_market']}/{'sponsor' if row['is_recognised_sponsor'] else 'other'}"
        by_stratum[key] = by_stratum.get(key, 0) + 1
    print(f"\nsampling {len(picked)} new rows:")
    for key in sorted(by_stratum):
        print(f"  {key:24s} {by_stratum[key]:4d}")
    cued = sum(1 for r in picked if r["mentions_visa"])
    print(f"  {'mentions a permit cue':24s} {cued:4d} / {len(picked)}")

    if args.dry_run:
        print("\n--dry-run: nothing written.")
        return

    combined = existing + [_to_record(row) for row in picked]
    save_golden_set(combined, args.out)
    print(f"\nwrote {len(combined)} rows -> {args.out}")
    print("Now fill in `visa_status_true` on each unlabelled line.")


if __name__ == "__main__":
    main()
