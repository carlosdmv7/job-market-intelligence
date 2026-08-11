"""Contract tests for the golden set and the replay provider."""

from __future__ import annotations

import pytest

from jmi_enrichment.models import LLMJobClassification
from jmi_evals.dataset import (
    GoldenRecord,
    RecordedResponse,
    load_golden_set,
    save_golden_set,
    text_hash,
)
from jmi_evals.metrics import evaluate
from jmi_evals.replay import MissingRecording, ReplayProvider
from jmi_evals.runner import check_thresholds

PROMPT = "Title: Data Engineer\n\nJob description:\nWe sponsor highly skilled migrants."


def _record(**overrides) -> GoldenRecord:
    base = {
        "content_hash": "a" * 64,
        "text_sha256": text_hash(PROMPT),
        "title": "Data Engineer",
        "prompt_input": PROMPT,
        "visa_status_true": "explicit_yes",
    }
    return GoldenRecord(**(base | overrides))


def test_roundtrip_preserves_labels(tmp_path):
    path = tmp_path / "golden.jsonl"
    save_golden_set([_record(), _record(content_hash="b" * 64, visa_status_true=None)], path)

    everything = load_golden_set(path)
    assert len(everything) == 2
    labelled = load_golden_set(path, labelled_only=True)
    assert len(labelled) == 1
    assert labelled[0].visa_status_true == "explicit_yes"


def test_check_text_catches_a_label_made_against_different_text():
    stale = _record(prompt_input="Completely different posting text.")
    with pytest.raises(ValueError, match="no longer matches"):
        stale.check_text()
    _record().check_text()  # matching text is fine


def test_missing_golden_set_says_how_to_make_one(tmp_path):
    with pytest.raises(FileNotFoundError, match=r"jmi_evals\.sample"):
        load_golden_set(tmp_path / "absent.jsonl")


def test_replay_provider_returns_the_recorded_classification():
    payload = {
        "normalized_role": "Data Engineer",
        "seniority": "senior",
        "visa": {"status": "explicit_yes", "confidence": 0.9, "evidence": "We sponsor"},
    }
    recording = RecordedResponse(
        content_hash="a" * 64,
        text_sha256=text_hash(PROMPT),
        model="gemini-2.5-flash-lite",
        prompt_version="enrich/v1",
        response=payload,
    )
    provider = ReplayProvider({recording.content_hash: recording})
    provider.current = "a" * 64

    parsed, usage = provider.classify(system="s", user="u", schema=LLMJobClassification)
    assert parsed.visa.status == "explicit_yes"
    assert usage.cost_usd == 0.0


def test_replay_provider_refuses_to_guess():
    provider = ReplayProvider({})
    provider.current = "missing"
    with pytest.raises(MissingRecording, match="--record"):
        provider.classify(system="s", user="u", schema=LLMJobClassification)

    provider.current = None
    with pytest.raises(MissingRecording, match="current"):
        provider.classify(system="s", user="u", schema=LLMJobClassification)


def test_thresholds_flag_a_regression_and_skip_absent_classes():
    labels = ["explicit_yes", "unclear"]
    report = evaluate(["unclear", "unclear"], ["unclear", "explicit_yes"], labels=labels)

    # accuracy is 0.5 here, so a 0.7 floor must fail...
    failures = check_thresholds(report, {"accuracy": 0.7})
    assert failures and "accuracy" in failures[0]

    # ...while a per-class rule for a class with no support is not asserted.
    assert check_thresholds(report, {"explicit_yes.recall": 0.9}) == []
    # Comment keys are ignored rather than treated as metrics.
    assert check_thresholds(report, {"_comment": 0.0, "accuracy": 0.1}) == []
