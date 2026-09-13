"""Run the classifier against the golden set and score it.

``--target`` picks the field being measured (see :mod:`jmi_evals.targets`).
It defaults to ``english`` — whether English alone is enough to do the job —
because that is the field whose classes are balanced enough to score and whose
answer changes whether a posting is worth applying to.

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
from jmi_evals.targets import DEFAULT_TARGET, TARGETS, Target

REPORT_PATH = EVALS_ROOT / "report.json"


def load_thresholds(
    path: Path = THRESHOLDS_PATH, *, target: str = DEFAULT_TARGET
) -> dict[str, float]:
    """The committed quality floor for one target.

    Keyed by target name, because a floor that made sense for one field says
    nothing about another: the visa floor was written when that field was the
    product and it is kept only to document what was once asserted.
    """
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8")).get(target, {})


def _predict(
    records: list[GoldenRecord],
    *,
    provider_name: str,
    target: Target,
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
        y_true.append(str(rec.label_for(target)))
        y_pred.append(target.predict(enrichment))
        sponsors.append(rec.is_recognised_sponsor)

    return y_true, y_pred, sponsors, skipped


class NothingToScore(RuntimeError):
    """The harness is wired but the data it needs does not exist yet.

    Distinct from a failing eval on purpose: "nobody has labelled anything"
    and "the classifier got worse" are different events and CI must not
    report them the same way.
    """


def run(
    provider_name: str = "replay", target_name: str = DEFAULT_TARGET
) -> tuple[EvalReport, list[str], Target]:
    target = TARGETS[target_name]
    records = load_golden_set(labelled_only=True, target=target)
    if not records:
        raise NothingToScore(
            f"no row is labelled for target '{target.name}' yet — run "
            f"`uv run python -m jmi_evals.label --target {target.name}`."
        )
    y_true, y_pred, sponsors, skipped = _predict(
        records, provider_name=provider_name, target=target
    )
    if not y_true:
        raise NothingToScore(
            "no labelled posting has a recorded response yet — run "
            "`uv run python -m jmi_evals.replay --record` once the daily pipeline "
            "has enriched some of them."
        )
    report = evaluate(y_true, y_pred, labels=list(target.labels))
    if target.reports_register_agreement:
        report.agreement = signal_agreement(y_pred, sponsors)
    return report, skipped, target


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
    parser.add_argument(
        "--target",
        choices=sorted(TARGETS),
        default=DEFAULT_TARGET,
        help="which classifier output to score (default: %(default)s)",
    )
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
        report, skipped, target = run(args.provider, args.target)
    except NothingToScore as exc:
        # Not a regression — there is simply nothing to measure yet. CI prints
        # this and stays green; pass --require-labels to make it a hard failure
        # once the golden set is expected to be populated.
        print(f"\nnothing to score: {exc}")
        raise SystemExit(1 if args.require_labels else 0) from None

    labelled_total = len(load_golden_set(labelled_only=True, target=target))

    print(f"\n{target.headline} — {report.n} labelled postings, provider={args.provider}\n")
    print(f"accuracy        {report.accuracy:.3f}")
    print(f"macro precision {report.macro_precision:.3f}")
    print(f"macro recall    {report.macro_recall:.3f}")
    print(f"macro F1        {report.macro_f1:.3f}\n")

    print(f"{'class':<16}{'support':>9}{'prec':>8}{'recall':>8}{'F1':>8}")
    for c in report.per_class:
        print(f"{c.label:<16}{c.support:>9}{c.precision:>8.3f}{c.recall:>8.3f}{c.f1:>8.3f}")

    print("\n" + format_confusion(report))

    if report.agreement:
        print("\nAgreement with the deterministic IND signal (a diagnostic, not a score):")
        for key, value in report.agreement.items():
            print(f"  {key:<38} {value}")

    if skipped:
        print(f"\nskipped {len(skipped)} postings without a recorded response")

    payload = report.to_dict() | {
        "target": target.name,
        "target_headline": target.headline,
        "provider": args.provider,
        "skipped": len(skipped),
        "golden_set_size": labelled_total,
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
    }
    args.out.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(f"\nreport -> {args.out}")

    if args.check:
        failures = check_thresholds(report, load_thresholds(target=target.name))
        if failures:
            print("\nTHRESHOLD FAILURES:")
            for f in failures:
                print(f"  - {f}")
            raise SystemExit(1)
        print("\nall committed thresholds met.")


if __name__ == "__main__":
    main()
