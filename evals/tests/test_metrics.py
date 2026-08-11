"""The metrics are the thing everything else is judged by, so they get tests."""

from __future__ import annotations

import pytest

from jmi_evals.metrics import evaluate, format_confusion, signal_agreement

LABELS = ["explicit_yes", "likely_yes", "unclear", "likely_no", "explicit_no"]


def test_perfect_prediction_scores_one():
    y = ["explicit_yes", "unclear", "explicit_no", "unclear"]
    report = evaluate(y, list(y), labels=LABELS)
    assert report.accuracy == 1.0
    assert report.macro_f1 == 1.0
    assert report.macro_precision == 1.0


def test_per_class_precision_recall_are_distinct():
    # Truth: 2 explicit_yes, 2 unclear. Model over-predicts explicit_yes.
    y_true = ["explicit_yes", "explicit_yes", "unclear", "unclear"]
    y_pred = ["explicit_yes", "unclear", "explicit_yes", "unclear"]
    report = evaluate(y_true, y_pred, labels=LABELS)
    by_label = {c.label: c for c in report.per_class}

    yes = by_label["explicit_yes"]
    assert yes.support == 2
    assert yes.predicted == 2
    assert yes.true_positives == 1
    assert yes.precision == 0.5
    assert yes.recall == 0.5
    assert report.accuracy == 0.5


def test_macro_average_ignores_classes_absent_from_truth():
    # 'likely_no' is never the truth, so it must not drag the macro F1 down.
    y_true = ["unclear", "unclear"]
    y_pred = ["unclear", "unclear"]
    report = evaluate(y_true, y_pred, labels=LABELS)
    assert report.macro_f1 == 1.0


def test_confusion_matrix_counts_rows_as_truth():
    y_true = ["explicit_yes", "explicit_yes"]
    y_pred = ["explicit_yes", "unclear"]
    report = evaluate(y_true, y_pred, labels=LABELS)
    assert report.confusion["explicit_yes"]["explicit_yes"] == 1
    assert report.confusion["explicit_yes"]["unclear"] == 1
    assert report.confusion["unclear"]["unclear"] == 0
    # Every label keeps a row and a column, so runs stay comparable.
    assert set(report.confusion) == set(LABELS)
    assert format_confusion(report).startswith("truth \\ pred")


def test_length_mismatch_and_empty_are_errors():
    with pytest.raises(ValueError, match="length mismatch"):
        evaluate(["unclear"], [], labels=LABELS)
    with pytest.raises(ValueError, match="empty"):
        evaluate([], [], labels=LABELS)


def test_signal_agreement_separates_the_two_directions():
    # Two recognised sponsors; the LLM finds sponsorship language in only one.
    # One non-sponsor the LLM wrongly calls positive — the number worth watching.
    statuses = ["explicit_yes", "unclear", "likely_yes", "unclear"]
    sponsors = [True, True, False, False]
    agreement = signal_agreement(statuses, sponsors)

    assert agreement["n"] == 4
    assert agreement["llm_positive"] == 2
    assert agreement["ind_positive"] == 2
    assert agreement["both_positive"] == 1
    # Half of the LLM's positives are at employers that can actually sponsor.
    assert agreement["llm_positive_confirmed_by_register"] == 0.5
    # Half of the recognised sponsors mention it in the text — expected to be low.
    assert agreement["register_positive_stated_in_text"] == 0.5


def test_signal_agreement_handles_no_positives():
    agreement = signal_agreement(["unclear", "unclear"], [False, False])
    assert agreement["llm_positive_confirmed_by_register"] is None
    assert agreement["register_positive_stated_in_text"] is None
    assert agreement["raw_agreement"] == 1.0
