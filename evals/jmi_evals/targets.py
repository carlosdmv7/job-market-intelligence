"""What the harness measures.

The eval was built around one field, ``visa.status``, because visa sponsorship
was the product. It isn't any more, and the measurement said so before the
product decision did: across 730 enriched postings the classifier's own output
was ``unclear`` 583 times and ``explicit_yes`` exactly once. A class that rare
cannot be scored — 14 labels produced precision 0.000 on ``explicit_yes`` not
because the model failed but because there was nothing there to find.

So the target is a parameter now. ``english`` is the default because it is the
field that is both *measurable* (the corpus splits 355 / 330 / 45, which is
close to balanced) and *useful*: whether English alone is enough to do the job
is the question that decides whether a posting is worth applying to.

The visa target is kept, not deleted. The labels already made against it stay
valid, and `--target visa` still scores them — the finding is part of the
project's record, and a harness that can only ever measure one field is a
harness that has to be rewritten the next time the product moves.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING, Any

from jmi_core.schema import VisaSponsorshipStatus

if TYPE_CHECKING:
    from jmi_evals.dataset import GoldenRecord


class EnglishSufficiency(StrEnum):
    """Ground-truth taxonomy for "can you do this job in English?".

    Three values, not a boolean, because the pipeline field is ``bool | None``
    and ``None`` carries real information: the posting did not say. Collapsing
    that into "no" would score silence as a negative finding.
    """

    YES = "yes"
    NO = "no"
    UNCLEAR = "unclear"


def _english_from_bool(value: bool | None) -> str:
    if value is None:
        return EnglishSufficiency.UNCLEAR.value
    return EnglishSufficiency.YES.value if value else EnglishSufficiency.NO.value


@dataclass(frozen=True, slots=True)
class Target:
    """One measurable field: where truth lives, and how to read the prediction."""

    name: str
    headline: str
    truth_field: str
    labels: tuple[str, ...]
    #: The IND-register cross-check only interprets the visa prediction.
    reports_register_agreement: bool = False

    def truth(self, record: GoldenRecord) -> str | None:
        value = getattr(record, self.truth_field)
        return None if value is None else str(value)

    def predict(self, enrichment: Any) -> str:
        if self.name == "visa":
            return str(enrichment.visa.status)
        return _english_from_bool(enrichment.english_sufficient)


ENGLISH = Target(
    name="english",
    headline="English-sufficiency classifier",
    truth_field="english_sufficient_true",
    labels=tuple(e.value for e in EnglishSufficiency),
)

VISA = Target(
    name="visa",
    headline="Visa classifier",
    truth_field="visa_status_true",
    labels=tuple(s.value for s in VisaSponsorshipStatus),
    reports_register_agreement=True,
)

TARGETS: dict[str, Target] = {t.name: t for t in (ENGLISH, VISA)}
DEFAULT_TARGET = ENGLISH.name
