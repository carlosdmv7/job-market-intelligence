"""End-to-end: golden set + recorded responses -> a scored report.

Exercises the path CI takes, with no warehouse, no network and no LLM, so a
break in the wiring shows up as a red unit test rather than as a silently
skipped eval job.
"""

from __future__ import annotations

import pytest

from jmi_evals import runner
from jmi_evals.dataset import GoldenRecord, RecordedResponse, text_hash
from jmi_evals.targets import VISA

PROMPTS = {
    "sponsor": "Title: Data Engineer\n\nJob description:\nWe sponsor visas for non-EU hires.",
    "refuses": "Title: Analyst\n\nJob description:\nYou must already hold an EU work permit.",
    "silent": "Title: BI Developer\n\nJob description:\nWe use dbt and Snowflake.",
}


def _golden(key: str, truth: str, *, sponsor: bool = False) -> GoldenRecord:
    return GoldenRecord(
        content_hash=key,
        text_sha256=text_hash(PROMPTS[key]),
        source="remotive",
        is_recognised_sponsor=sponsor,
        visa_status_true=truth,
        prompt_input=PROMPTS[key],
    )


def _recorded(key: str, predicted: str) -> RecordedResponse:
    return RecordedResponse(
        content_hash=key,
        text_sha256=text_hash(PROMPTS[key]),
        model="gemini-2.5-flash-lite",
        prompt_version="enrich/v1",
        response={"visa": {"status": predicted, "confidence": 0.8, "evidence": None}},
    )


@pytest.fixture
def wired(monkeypatch):
    """Install a golden set and matching recordings into the runner."""

    def install(golden, recordings):
        monkeypatch.setattr(
            runner,
            "load_golden_set",
            lambda **kw: [g for g in golden if g.is_labelled_for(VISA)],
        )
        monkeypatch.setattr(
            runner, "load_responses", lambda: {r.content_hash: r for r in recordings}
        )

    return install


def test_scores_a_perfect_replay(wired):
    golden = [
        _golden("sponsor", "explicit_yes", sponsor=True),
        _golden("refuses", "explicit_no"),
        _golden("silent", "unclear"),
    ]
    wired(golden, [_recorded(k, g.visa_status_true) for k, g in zip(PROMPTS, golden, strict=True)])

    report, skipped, _ = runner.run("replay", "visa")
    assert report.n == 3
    assert report.accuracy == 1.0
    assert skipped == []
    # The agreement diagnostic travels with the report.
    assert report.agreement["ind_positive"] == 1
    assert report.agreement["llm_positive_confirmed_by_register"] == 1.0


def test_a_regression_trips_a_threshold(wired):
    golden = [_golden("sponsor", "explicit_yes"), _golden("refuses", "explicit_no")]
    # The model has started calling everything 'unclear'.
    wired(golden, [_recorded("sponsor", "unclear"), _recorded("refuses", "unclear")])

    report, _, _ = runner.run("replay", "visa")
    assert report.accuracy == 0.0
    floor = {"accuracy": 0.7, "explicit_no.recall": 0.5}
    failures = runner.check_thresholds(report, floor)
    assert failures, "a floor must catch a total classifier failure"


def test_retired_thresholds_document_rather_than_gate():
    """A metric nobody intends to meet again must not be able to fail a build.

    The visa floor is kept as the record of what was once asserted (ADR 0007),
    nested under a comment key so `load_thresholds` returns no live gate for it
    — otherwise `make evals TARGET=visa` would go red forever on a class the
    corpus contains once in 730 postings.
    """
    visa = runner.load_thresholds(target="visa")
    assert not [k for k in visa if not k.startswith("_")]
    assert visa["_retired_floor"]["explicit_yes.precision"] == 0.6


def test_postings_without_a_recording_are_skipped_not_guessed(wired):
    golden = [_golden("sponsor", "explicit_yes"), _golden("silent", "unclear")]
    wired(golden, [_recorded("sponsor", "explicit_yes")])

    report, skipped, _ = runner.run("replay", "visa")
    assert report.n == 1
    assert skipped == ["silent"]


def test_unlabelled_golden_set_is_not_a_failure(wired):
    wired([], [])
    with pytest.raises(runner.NothingToScore, match="no row is labelled for target"):
        runner.run("replay", "visa")


def test_text_drift_since_labelling_is_an_error(wired, monkeypatch):
    stale = _golden("sponsor", "explicit_yes")
    stale.prompt_input = "A completely different posting."
    wired([stale], [_recorded("sponsor", "explicit_yes")])

    with pytest.raises(ValueError, match="no longer matches"):
        runner.run("replay", "visa")
