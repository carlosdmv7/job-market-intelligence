"""Classification metrics, computed here rather than pulled in from sklearn.

The whole file is ~100 lines of arithmetic; a scikit-learn dependency for it
would be the largest package in the project and would pull BLAS into a stack
whose selling point is that it runs at 0€ on a free tier. Implementing it also
means the definitions are visible and testable, which is the point of an eval
harness in the first place.

Averaging convention: **macro** (unweighted mean over classes present in the
truth), because the rare classes — ``explicit_yes`` and ``explicit_no`` — are
exactly the ones the product cares about. A micro average would let the
overwhelming ``unclear`` majority hide a total failure on them.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class ClassMetrics:
    label: str
    support: int
    predicted: int
    true_positives: int

    @property
    def precision(self) -> float:
        return self.true_positives / self.predicted if self.predicted else 0.0

    @property
    def recall(self) -> float:
        return self.true_positives / self.support if self.support else 0.0

    @property
    def f1(self) -> float:
        p, r = self.precision, self.recall
        return 2 * p * r / (p + r) if (p + r) else 0.0


@dataclass(slots=True)
class EvalReport:
    n: int
    accuracy: float
    macro_precision: float
    macro_recall: float
    macro_f1: float
    per_class: list[ClassMetrics]
    confusion: dict[str, dict[str, int]]
    labels: list[str]
    #: Agreement between the LLM and the deterministic IND signal — a
    #: diagnostic, never a score. See :func:`signal_agreement`.
    agreement: dict[str, float | int | None] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "n": self.n,
            "accuracy": round(self.accuracy, 4),
            "macro_precision": round(self.macro_precision, 4),
            "macro_recall": round(self.macro_recall, 4),
            "macro_f1": round(self.macro_f1, 4),
            "per_class": {
                c.label: {
                    "support": c.support,
                    "predicted": c.predicted,
                    "precision": round(c.precision, 4),
                    "recall": round(c.recall, 4),
                    "f1": round(c.f1, 4),
                }
                for c in self.per_class
            },
            "confusion": self.confusion,
            "agreement": self.agreement,
        }


def evaluate(
    y_true: list[str],
    y_pred: list[str],
    *,
    labels: list[str] | None = None,
) -> EvalReport:
    """Per-class precision/recall/F1 + the full confusion matrix.

    ``labels`` fixes the row/column order so the matrix is comparable between
    runs; classes absent from both lists are dropped from the macro average so
    an unpopulated class cannot drag the score to zero.
    """
    if len(y_true) != len(y_pred):
        raise ValueError(f"length mismatch: {len(y_true)} truths vs {len(y_pred)} predictions")
    if not y_true:
        raise ValueError("cannot evaluate an empty set")

    order = labels or sorted(set(y_true) | set(y_pred))
    truth_counts, pred_counts = Counter(y_true), Counter(y_pred)
    hits = Counter(t for t, p in zip(y_true, y_pred, strict=True) if t == p)

    confusion = {t: dict.fromkeys(order, 0) for t in order}
    for t, p in zip(y_true, y_pred, strict=True):
        confusion[t][p] += 1

    per_class = [
        ClassMetrics(
            label=label,
            support=truth_counts.get(label, 0),
            predicted=pred_counts.get(label, 0),
            true_positives=hits.get(label, 0),
        )
        for label in order
    ]
    # Macro average over classes that actually occur in the ground truth.
    scored = [c for c in per_class if c.support > 0]
    n_scored = len(scored) or 1

    return EvalReport(
        n=len(y_true),
        accuracy=sum(hits.values()) / len(y_true),
        macro_precision=sum(c.precision for c in scored) / n_scored,
        macro_recall=sum(c.recall for c in scored) / n_scored,
        macro_f1=sum(c.f1 for c in scored) / n_scored,
        per_class=per_class,
        confusion=confusion,
        labels=order,
    )


#: Statuses that assert the posting offers sponsorship.
POSITIVE_STATUSES = frozenset({"explicit_yes", "likely_yes"})


def signal_agreement(
    statuses: list[str],
    recognised_sponsor: list[bool],
) -> dict[str, float | int | None]:
    """How often the LLM's text read lines up with the IND register match.

    This is **not** an accuracy measure and a low number is not a bug. The two
    signals answer different questions:

    * the register says whether the *employer* is legally allowed to sponsor;
    * the LLM says whether *this posting's text* mentions sponsorship.

    A recognised sponsor that simply doesn't discuss visas in the ad is the
    normal case, and it is precisely why the deterministic signal is the
    primary one. What the number is good for is spotting the reverse error —
    the LLM claiming sponsorship at a company that legally cannot sponsor —
    which is a real red flag worth watching over time.
    """
    if len(statuses) != len(recognised_sponsor):
        raise ValueError("statuses and recognised_sponsor must be the same length")

    pairs = list(zip(statuses, recognised_sponsor, strict=True))
    llm_pos = [(s, r) for s, r in pairs if s in POSITIVE_STATUSES]
    ind_pos = [(s, r) for s, r in pairs if r]

    both = sum(1 for s, r in pairs if (s in POSITIVE_STATUSES) and r)
    neither = sum(1 for s, r in pairs if (s not in POSITIVE_STATUSES) and not r)

    return {
        "n": len(pairs),
        "llm_positive": len(llm_pos),
        "ind_positive": len(ind_pos),
        "both_positive": both,
        "raw_agreement": round((both + neither) / len(pairs), 4) if pairs else 0.0,
        # Of the postings the LLM calls sponsoring, how many are at an employer
        # that actually can sponsor. The one to watch.
        "llm_positive_confirmed_by_register": (round(both / len(llm_pos), 4) if llm_pos else None),
        # Of the recognised sponsors, how many say so in the text. Expected low.
        "register_positive_stated_in_text": (round(both / len(ind_pos), 4) if ind_pos else None),
    }


def format_confusion(report: EvalReport) -> str:
    """Confusion matrix as a fixed-width table (rows = truth, cols = predicted)."""
    labels = report.labels
    width = max([len(x) for x in labels] + [12])
    head = "truth \\ pred".ljust(width) + "".join(x[:11].rjust(12) for x in labels)
    lines = [head, "-" * len(head)]
    for t in labels:
        row = t.ljust(width) + "".join(str(report.confusion[t][p]).rjust(12) for p in labels)
        lines.append(row)
    return "\n".join(lines)
