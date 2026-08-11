"""Run the visa classifier against the golden set and score it.

Two modes, same code path:

``--provider replay`` (the CI default)
    Replays recorded responses. Offline, deterministic, free. Scores only the
    postings that have a recording, and fails the build if any committed
    threshold is missed.

``--provider live``
    Calls the configured LLM for real. Use this after a prompt change to see
    what actually moved, then re-record and re-commit the fixtures.

The report is written to ``evals/report.json`` and — because a number nobody
reads is a number nobody trusts — surfaced on the app's "How it works" page.
"""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path

from jmi_core.schema import VisaSponsorshipStatus
from jmi_enrichment.classifier import JobClassifier
from jmi_enrichment.providers import ClassificationError
from jmi_evals.dataset import (
    EVALS_ROOT,
    THRESHOLDS_PATH,
    GoldenRecord,
    load_golden_set,
    load_responses,
)
from jmi_evals.metrics import EvalReport, evaluate, format_confusion, signal_agreement
from jmi_evals.replay import ReplayProvider

REPORT_PATH = EVALS_ROOT / "report.json"

#: Fixed label order, so the confusion matrix reads good -> bad every run.
LABELS = [s.value for s in VisaSponsorshipStatus]


def load_thresholds(path: Path = THRESHOLDS_PATH) -> dict[str, float]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _predict(
    records: list[GoldenRecord],
    *,
    provider_name: str,
) -> tuple[list[str], list[str], list[bool], list[str]]:
    """Return (y_true, y_pred, recognised_sponsor, skipped) for scorable rows."""
    from jmi_core.settings import get_settings

    settings = get_settings()

    if provider_name == "replay":
        recordings = load_responses()
        provider = ReplayProvider(recordings)
        classifier = JobClassifier(settings, provider=provider)
    else:
        classifier = JobClassifier(settings)
        provider = None

    y_true: list[str] = []
    y_pred: list[str] = []
    sponsors: list[bool] = []
    skipped: list[str] = []

    for rec in records:
        rec.check_text()
        if provider is not None:
            if rec.content_hash not in provider.recordings:
                skipped.append(rec.content_hash)
                continue
            provider.current = rec.content_hash
        posting = {
            "content_hash": rec.content_hash,
            # The enrichment contract requires a known source; the golden set
            # always carries one, but fall back rather than crash a scoring run.
            "source": rec.source or "remotive",
            "source_job_id": rec.content_hash,
            "description_raw": rec.prompt_input,
        }
        try:
            enrichment = classifier.classify_rendered(posting, rec.prompt_input)
        except ClassificationError as exc:
            skipped.append(f"{rec.content_hash} ({exc})")
            continue
        y_true.append(str(rec.visa_status_true))
        y_pred.append(str(enrichment.visa.status))
        sponsors.append(rec.is_recognised_sponsor)

    return y_true, y_pred, sponsors, skipped


class NothingToScore(RuntimeError):
    """The harness is wired but the data it needs does not exist yet.

    Distinct from a failing eval on purpose: "nobody has labelled anything"
    and "the classifier got worse" are different events and CI must not
    report them the same way.
    """


def run(provider_name: str = "replay") -> tuple[EvalReport, list[str]]:
    records = load_golden_set(labelled_only=True)
    if not records:
        raise NothingToScore(
            "the golden set has no labelled rows yet — fill in `visa_status_true` "
            "in evals/golden_set.jsonl."
        )
    y_true, y_pred, sponsors, skipped = _predict(records, provider_name=provider_name)
    if not y_true:
        raise NothingToScore(
            "no labelled posting has a recorded response yet — run "
            "`uv run python -m jmi_evals.replay --record` once the daily pipeline "
            "has enriched some of them."
        )
    report = evaluate(y_true, y_pred, labels=LABELS)
    report.agreement = signal_agreement(y_pred, sponsors)
    return report, skipped


def check_thresholds(report: EvalReport, thresholds: dict[str, float]) -> list[str]:
    """Return a list of human-readable failures (empty = pass)."""
    failures: list[str] = []
    by_class = {c.label: c for c in report.per_class}
    for key, minimum in thresholds.items():
        if key.startswith("_"):  # comment keys
            continue
        if "." in key:
            label, metric = key.split(".", 1)
            cls = by_class.get(label)
            if cls is None or cls.support == 0:
                continue  # class absent from the labelled set — nothing to assert
            actual = getattr(cls, metric)
        else:
            actual = getattr(report, key, None)
            if actual is None:
                continue
        if actual < minimum:
            failures.append(f"{key}: {actual:.3f} < required {minimum:.3f}")
    return failures


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--provider", choices=["replay", "live"], default="replay")
    parser.add_argument("--out", type=Path, default=REPORT_PATH)
    parser.add_argument(
        "--check",
        action="store_true",
        help="exit non-zero if a committed threshold is missed (used by CI)",
    )
    parser.add_argument(
        "--require-labels",
        action="store_true",
        help="treat an unlabelled golden set as a failure instead of a notice",
    )
    args = parser.parse_args()

    try:
        report, skipped = run(args.provider)
    except NothingToScore as exc:
        # Not a regression — there is simply nothing to measure yet. CI prints
        # this and stays green; pass --require-labels to make it a hard failure
        # once the golden set is expected to be populated.
        print(f"\nnothing to score: {exc}")
        raise SystemExit(1 if args.require_labels else 0) from None

    labelled_total = len(load_golden_set())

    print(f"\nVisa classifier — {report.n} labelled postings, provider={args.provider}\n")
    print(f"accuracy        {report.accuracy:.3f}")
    print(f"macro precision {report.macro_precision:.3f}")
    print(f"macro recall    {report.macro_recall:.3f}")
    print(f"macro F1        {report.macro_f1:.3f}\n")

    print(f"{'class':<16}{'support':>9}{'prec':>8}{'recall':>8}{'F1':>8}")
    for c in report.per_class:
        print(f"{c.label:<16}{c.support:>9}{c.precision:>8.3f}{c.recall:>8.3f}{c.f1:>8.3f}")

    print("\n" + format_confusion(report))

    print("\nAgreement with the deterministic IND signal (a diagnostic, not a score):")
    for key, value in report.agreement.items():
        print(f"  {key:<38} {value}")

    if skipped:
        print(f"\nskipped {len(skipped)} postings without a recorded response")

    payload = report.to_dict() | {
        "provider": args.provider,
        "skipped": len(skipped),
        "golden_set_size": labelled_total,
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
    }
    args.out.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(f"\nreport -> {args.out}")

    if args.check:
        failures = check_thresholds(report, load_thresholds())
        if failures:
            print("\nTHRESHOLD FAILURES:")
            for f in failures:
                print(f"  - {f}")
            raise SystemExit(1)
        print("\nall committed thresholds met.")


if __name__ == "__main__":
    main()
