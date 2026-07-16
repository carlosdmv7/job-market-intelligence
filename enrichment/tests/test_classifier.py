"""Classifier wiring tests with a fake provider (no network)."""

from __future__ import annotations

from jmi_core.schema import RemotePolicy, Seniority, VisaSponsorship, VisaSponsorshipStatus
from jmi_core.settings import Settings
from jmi_enrichment.classifier import JobClassifier
from jmi_enrichment.models import LLMJobClassification
from jmi_enrichment.providers import ClassificationError, LLMUsage

POSTING = {
    "content_hash": "abc123",
    "source": "remotive",
    "source_job_id": "r-1",
    "title": "Analytics Engineer",
    "company_name": "Acme",
    "location_raw": "Amsterdam",
    "country_code": "NL",
    "salary_raw": "€60.000-€75.000",
    "description_raw": "We sponsor visas. dbt + Snowflake.",
    "detected_language": "en",
}


def _classification() -> LLMJobClassification:
    return LLMJobClassification(
        normalized_role="Analytics Engineer",
        role_family="Data Engineering",
        seniority=Seniority.MID,
        remote_policy=RemotePolicy.REMOTE,
        technologies=["dbt", "snowflake"],
        visa=VisaSponsorship(
            status=VisaSponsorshipStatus.EXPLICIT_YES, confidence=0.95, evidence="We sponsor visas."
        ),
        english_sufficient=True,
        enrichment_confidence=0.9,
    )


class FakeProvider:
    model = "qwen2.5:7b"

    def __init__(self, result=None, *, raise_error=False):
        self._result = result or _classification()
        self._raise = raise_error
        self.calls: list[dict] = []

    def classify(self, *, system, user, schema):
        self.calls.append({"system": system, "user": user, "schema": schema})
        if self._raise:
            raise ClassificationError("boom")
        return self._result, LLMUsage(input_tokens=300, output_tokens=120, cost_usd=0.0)


def test_classify_builds_full_enrichment():
    provider = FakeProvider()
    clf = JobClassifier(Settings(), provider=provider)
    e = clf.classify(POSTING)

    assert e.content_hash == "abc123"
    assert e.source.value == "remotive"
    assert e.model == "qwen2.5:7b"
    assert e.cost_usd == 0.0  # local model is free
    assert e.input_tokens == 300
    assert e.visa.status is VisaSponsorshipStatus.EXPLICIT_YES
    assert e.raw_response["technologies"] == ["dbt", "snowflake"]

    # system carries the taxonomy; user carries the JSON-shape instructions.
    call = provider.calls[0]
    assert "visa.status" in call["system"]
    assert "Respond with ONLY a JSON object" in call["user"]


def test_classify_many_skips_failures():
    clf = JobClassifier(Settings(), provider=FakeProvider(raise_error=True))
    assert list(clf.classify_many([POSTING, POSTING])) == []


def test_classify_many_opens_circuit_on_consecutive_failures():
    """An exhausted quota must not burn a retry cycle per remaining posting."""
    provider = FakeProvider(raise_error=True)
    clf = JobClassifier(Settings(), provider=provider)
    batch = [POSTING] * (JobClassifier.MAX_CONSECUTIVE_FAILURES * 3)

    assert list(clf.classify_many(batch)) == []
    assert len(provider.calls) == JobClassifier.MAX_CONSECUTIVE_FAILURES


def test_classify_many_success_resets_the_circuit():
    class FlakyProvider(FakeProvider):
        def classify(self, *, system, user, schema):
            # fail, succeed, fail, succeed, ... — never 5 consecutive failures
            flaky = len(self.calls) % 2 == 0
            self.calls.append({})
            if flaky:
                raise ClassificationError("boom")
            return self._result, LLMUsage(input_tokens=1, output_tokens=1, cost_usd=0.0)

    provider = FlakyProvider()
    clf = JobClassifier(Settings(), provider=provider)
    out = list(clf.classify_many([POSTING] * 12))
    assert len(out) == 6  # every other call succeeds; the circuit never opens
    assert len(provider.calls) == 12
