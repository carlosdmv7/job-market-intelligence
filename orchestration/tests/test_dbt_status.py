"""The run summary the app's freshness header depends on."""

from __future__ import annotations

from jmi_flows.dbt_status import summarize


def _result(unique_id: str, status: str) -> dict:
    return {"unique_id": unique_id, "status": status}


def test_summarize_separates_tests_from_models():
    summary = summarize(
        {
            "metadata": {"dbt_version": "1.11.11", "generated_at": "2026-09-13T09:00:00Z"},
            "elapsed_time": 4.27,
            "results": [
                _result("test.jmi.not_null_x", "pass"),
                _result("test.jmi.unique_x", "pass"),
                _result("model.jmi.FT_JOB_POSTING", "success"),
            ],
        }
    )
    assert (summary["tests_total"], summary["tests_passed"]) == (2, 2)
    assert (summary["models_total"], summary["models_passed"]) == (1, 1)
    assert summary["dbt_version"] == "1.11.11"
    assert summary["elapsed_seconds"] == 4.3


def test_summarize_counts_a_failed_test_as_not_passed():
    summary = summarize({"results": [_result("test.jmi.a", "pass"), _result("test.jmi.b", "fail")]})
    assert (summary["tests_total"], summary["tests_passed"]) == (2, 1)


def test_summarize_survives_an_empty_run():
    # A run that died before dbt produced anything must still summarize, so the
    # pipeline can record that it died rather than crashing on the way out.
    summary = summarize({})
    assert summary["tests_total"] == 0
    assert summary["elapsed_seconds"] == 0.0
