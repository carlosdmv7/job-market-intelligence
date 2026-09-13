"""The golden set: the committed contract the visa classifier is measured against.

One JSON object per line. The fields are ordered so a human labelling the file
in an editor sees the identifiers, then the label to fill in, then the notes,
and only then the long posting text — which is stored inline on purpose:

* the eval runner needs no warehouse, so CI can run fully offline;
* the text is pinned, so a re-scrape or a truncation change cannot silently
  move the ground truth out from under a label. ``text_sha256`` makes that
  drift an error instead of a mystery.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from jmi_core.schema import VisaSponsorshipStatus
from jmi_evals.targets import DEFAULT_TARGET, TARGETS, EnglishSufficiency, Target

EVALS_ROOT = Path(__file__).resolve().parents[1]
GOLDEN_SET_PATH = EVALS_ROOT / "golden_set.jsonl"
RESPONSES_PATH = EVALS_ROOT / "fixtures" / "responses.jsonl"
THRESHOLDS_PATH = EVALS_ROOT / "thresholds.json"


def text_hash(prompt_input: str) -> str:
    """Stable hash of the exact text the classifier is shown."""
    return hashlib.sha256(prompt_input.encode("utf-8")).hexdigest()


class GoldenRecord(BaseModel):
    """One hand-labelled posting.

    The ``*_true`` fields are the labels — ``None`` in a freshly sampled file,
    and the only fields a human is expected to edit (plus ``notes``). One row
    can carry a label for more than one target; they are independent, so a row
    labelled for ``english`` and not for ``visa`` is normal, not incomplete.
    Everything else is provenance, and changing it by hand invalidates a label.
    """

    model_config = ConfigDict(extra="forbid")

    content_hash: str
    text_sha256: str
    title: str | None = None
    company_name: str | None = None
    country_code: str | None = None
    source: str | None = None
    source_url: str | None = None

    #: The deterministic IND register match at sampling time. Never ground
    #: truth for the LLM — it answers a different question (is this *employer*
    #: allowed to sponsor?) than the text does (does this *posting* say so?).
    is_recognised_sponsor: bool = False

    #: What production said when the row was sampled, for drift analysis only.
    llm_status_at_sampling: VisaSponsorshipStatus | None = None

    #: Label for the ``visa`` target. Kept: the labels made against it are
    #: still valid, even though the corpus turned out too one-sided to score.
    visa_status_true: VisaSponsorshipStatus | None = None

    #: Label for the ``english`` target — can you do this job in English?
    english_sufficient_true: EnglishSufficiency | None = None

    notes: str = ""

    #: The exact user-prompt input, rendered by ``build_user_prompt``.
    prompt_input: str = ""

    def label_for(self, target: Target) -> str | None:
        return target.truth(self)

    def is_labelled_for(self, target: Target) -> bool:
        return self.label_for(target) is not None

    def check_text(self) -> None:
        actual = text_hash(self.prompt_input)
        if actual != self.text_sha256:
            raise ValueError(
                f"{self.content_hash[:12]}: prompt_input no longer matches text_sha256 "
                f"({actual[:12]} != {self.text_sha256[:12]}). The label was made against "
                "different text — re-label or restore the original."
            )


def load_golden_set(
    path: Path = GOLDEN_SET_PATH,
    *,
    labelled_only: bool = False,
    target: str | Target = DEFAULT_TARGET,
) -> list[GoldenRecord]:
    if not path.exists():
        raise FileNotFoundError(
            f"no golden set at {path}. Generate the template first:\n"
            "    uv run python -m jmi_evals.sample --size 200"
        )
    records = [
        GoldenRecord.model_validate_json(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    if not labelled_only:
        return records
    resolved = TARGETS[target] if isinstance(target, str) else target
    return [r for r in records if r.is_labelled_for(resolved)]


def save_golden_set(records: list[GoldenRecord], path: Path = GOLDEN_SET_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [json.dumps(r.model_dump(mode="json"), ensure_ascii=False) for r in records]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


# --- recorded model responses (the CI replay cache) -------------------------
class RecordedResponse(BaseModel):
    """One real model output, replayed in CI instead of calling a provider."""

    model_config = ConfigDict(extra="forbid")

    content_hash: str
    text_sha256: str
    model: str
    prompt_version: str
    response: dict[str, Any] = Field(description="The validated LLMJobClassification payload")


def load_responses(path: Path = RESPONSES_PATH) -> dict[str, RecordedResponse]:
    """Keyed by ``content_hash``. Missing file = empty cache, not an error."""
    if not path.exists():
        return {}
    out: dict[str, RecordedResponse] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rec = RecordedResponse.model_validate_json(line)
            out[rec.content_hash] = rec
    return out


def save_responses(responses: list[RecordedResponse], path: Path = RESPONSES_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [json.dumps(r.model_dump(mode="json"), ensure_ascii=False) for r in responses]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
