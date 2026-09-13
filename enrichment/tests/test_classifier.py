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
    clf = JobClassifier(
        Settings(JMI_ENRICHMENT_POSTINGS_PER_REQUEST=1),
        provider=FakeProvider(raise_error=True),
    )
    assert list(clf.classify_many([POSTING, POSTING])) == []


def test_classify_many_opens_circuit_on_consecutive_failures():
    """An exhausted quota must not burn a retry cycle per remaining posting.

    Pinned to one posting per request: this asserts the failure *count*, and
    batching would otherwise change how many postings each failure represents.
    """
    provider = FakeProvider(raise_error=True)
    clf = JobClassifier(Settings(JMI_ENRICHMENT_POSTINGS_PER_REQUEST=1), provider=provider)
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
    clf = JobClassifier(Settings(JMI_ENRICHMENT_POSTINGS_PER_REQUEST=1), provider=provider)
    out = list(clf.classify_many([POSTING] * 12))
    assert len(out) == 6  # every other call succeeds; the circuit never opens
    assert len(provider.calls) == 12


# --- batched requests -------------------------------------------------------
def _posting(n: int) -> dict:
    return POSTING | {
        "content_hash": f"hash{n}",
        "source_job_id": f"r-{n}",
        "title": f"Data Engineer {n}",
    }


class FakeBatchProvider:
    """Returns a caller-supplied batch payload, recording every request."""

    model = "gemini-2.5-flash-lite"

    def __init__(self, payload, *, usage=None):
        self._payload = payload
        self._usage = usage or LLMUsage(input_tokens=3000, output_tokens=1200, cost_usd=0.02)
        self.calls: list[dict] = []

    def classify(self, *, system, user, schema):
        self.calls.append({"system": system, "user": user, "schema": schema})
        return schema.model_validate(self._payload), self._usage


def _batch(*indices: int) -> dict:
    return {
        "results": [
            {"index": i, "classification": _classification().model_dump(mode="json")}
            for i in indices
        ]
    }


def test_a_batch_costs_one_request_and_returns_every_posting():
    provider = FakeBatchProvider(_batch(1, 2, 3))
    clf = JobClassifier(Settings(), provider=provider)

    results = clf.classify_batch([_posting(1), _posting(2), _posting(3)])

    assert len(provider.calls) == 1, "the whole point is one request for the whole batch"
    assert [e.content_hash for e in results] == ["hash1", "hash2", "hash3"]


def test_results_are_matched_by_index_not_by_position():
    # The silent-corruption case: a model that answers out of order would, under
    # positional matching, attach every classification to the wrong posting.
    provider = FakeBatchProvider(_batch(3, 1, 2))
    clf = JobClassifier(Settings(), provider=provider)

    results = clf.classify_batch([_posting(1), _posting(2), _posting(3)])

    assert [e.content_hash for e in results] == ["hash3", "hash1", "hash2"]


def test_a_dropped_posting_leaves_the_others_correct():
    provider = FakeBatchProvider(_batch(1, 3))
    clf = JobClassifier(Settings(), provider=provider)

    results = clf.classify_batch([_posting(1), _posting(2), _posting(3)])

    # Posting 2 is simply not returned — it stays pending rather than being
    # guessed or silently given posting 3's classification.
    assert [e.content_hash for e in results] == ["hash1", "hash3"]


def test_out_of_range_and_duplicate_indices_are_discarded():
    provider = FakeBatchProvider(_batch(1, 1, 9))
    clf = JobClassifier(Settings(), provider=provider)

    results = clf.classify_batch([_posting(1), _posting(2)])

    assert [e.content_hash for e in results] == ["hash1"]


def test_usage_is_divided_across_the_batch_so_totals_stay_additive():
    provider = FakeBatchProvider(
        _batch(1, 2, 3, 4), usage=LLMUsage(input_tokens=4000, output_tokens=800, cost_usd=0.04)
    )
    clf = JobClassifier(Settings(), provider=provider)

    results = clf.classify_batch([_posting(i) for i in (1, 2, 3, 4)])

    assert [e.input_tokens for e in results] == [1000, 1000, 1000, 1000]
    assert sum(e.cost_usd for e in results) == 0.04


def test_classify_many_groups_postings_into_whole_requests():
    provider = FakeBatchProvider(_batch(1, 2))
    settings = Settings(JMI_ENRICHMENT_POSTINGS_PER_REQUEST=2)
    clf = JobClassifier(settings, provider=provider)

    results = list(clf.classify_many([_posting(i) for i in (1, 2, 3, 4)]))

    assert len(provider.calls) == 2, "four postings, two per request"
    assert len(results) == 4


def test_one_per_request_keeps_the_single_posting_path():
    provider = FakeProvider()
    settings = Settings(JMI_ENRICHMENT_POSTINGS_PER_REQUEST=1)
    clf = JobClassifier(settings, provider=provider)

    results = list(clf.classify_many([_posting(1), _posting(2)]))

    assert len(results) == 2
    assert provider.calls[0]["schema"] is LLMJobClassification, "not the batch envelope"


def test_a_failing_batch_counts_as_one_failure_not_ten():
    # The circuit breaker guards against a provider that stopped answering, which
    # is a property of the request. Counting each posting in a failed batch would
    # trip it on the first group and abandon the run.
    class Failing:
        model = "m"

        def __init__(self):
            self.calls = 0

        def classify(self, *, system, user, schema):
            self.calls += 1
            raise ClassificationError("quota exhausted")

    provider = Failing()
    settings = Settings(JMI_ENRICHMENT_POSTINGS_PER_REQUEST=2)
    clf = JobClassifier(settings, provider=provider)

    assert list(clf.classify_many([_posting(i) for i in range(1, 21)])) == []
    assert provider.calls == JobClassifier.MAX_CONSECUTIVE_FAILURES
