"""Provider-agnostic classifier: posting row -> JobEnrichment.

Wraps an :class:`~jmi_enrichment.providers.LLMProvider` (Gemini by default).
The provider returns a validated :class:`LLMJobClassification` + usage; this
class adds lineage/cost metadata and builds the full ``JobEnrichment``.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from jmi_core import SCHEMA_VERSION
from jmi_core.logging import get_logger
from jmi_core.schema import JobEnrichment, JobSource
from jmi_enrichment.models import LLMBatchClassification, LLMJobClassification
from jmi_enrichment.prompts import (
    SYSTEM_PROMPT,
    batch_json_output_instructions,
    build_batch_user_prompt,
    build_user_prompt,
    json_output_instructions,
)
from jmi_enrichment.providers import (
    ClassificationError,
    LLMProvider,
    LLMUsage,
    get_provider,
)

if TYPE_CHECKING:
    from collections.abc import Iterable, Iterator

    from jmi_core.settings import Settings

log = get_logger(__name__)


class JobClassifier:
    def __init__(self, settings: Settings, *, provider: LLMProvider | None = None):
        self.settings = settings
        self.provider = provider or get_provider(settings)
        self.prompt_version = settings.enrichment_prompt_version
        self.postings_per_request = settings.enrichment_postings_per_request

    def classify(self, posting: dict[str, Any]) -> JobEnrichment:
        return self.classify_rendered(posting, build_user_prompt(posting))

    def classify_rendered(self, posting: dict[str, Any], user_prompt: str) -> JobEnrichment:
        """Classify from an already-rendered user prompt.

        The eval harness needs this: its golden set pins the exact prompt text
        each label was made against, so re-rendering from fields would let a
        change in ``build_user_prompt`` alter the input under a fixed label.
        """
        user = user_prompt + "\n\n" + json_output_instructions()
        result, usage = self.provider.classify(
            system=SYSTEM_PROMPT, user=user, schema=LLMJobClassification
        )
        return self._to_enrichment(posting, result, usage)

    def classify_batch(self, postings: list[dict[str, Any]]) -> list[JobEnrichment]:
        """Classify several postings in one request.

        Returns only the postings the model actually answered for, matched by
        the echoed index rather than by position — a response that dropped or
        reordered an entry would otherwise write each classification onto the
        wrong job, which is silent and unrecoverable.

        A short response is **not** retried one-by-one. The quota this exists to
        stretch is counted in requests, so re-asking individually would spend a
        whole day's budget to recover a few rows. The unanswered postings simply
        stay pending and the next run picks them up.
        """
        if not postings:
            return []
        user = (
            build_batch_user_prompt(postings)
            + "\n\n"
            + batch_json_output_instructions(len(postings))
        )
        batch, usage = self.provider.classify(
            system=SYSTEM_PROMPT, user=user, schema=LLMBatchClassification
        )

        enrichments: list[JobEnrichment] = []
        seen: set[int] = set()
        for item in batch.results:
            if item.index > len(postings) or item.index in seen:
                log.warning("enrich.batch.bad_index", index=item.index, requested=len(postings))
                continue
            seen.add(item.index)
            enrichments.append(
                self._to_enrichment(
                    postings[item.index - 1],
                    item.classification,
                    _share_usage(usage, len(batch.results)),
                )
            )
        if len(enrichments) < len(postings):
            log.warning(
                "enrich.batch.partial",
                requested=len(postings),
                returned=len(enrichments),
            )
        return enrichments

    #: Consecutive provider failures after which the batch aborts. When a
    #: free-tier daily quota is exhausted, every remaining posting would burn
    #: ~a minute of retries just to fail — skipped rows stay pending and the
    #: next scheduled run picks them up, so giving up early loses nothing.
    MAX_CONSECUTIVE_FAILURES = 5

    def classify_many(self, postings: Iterable[dict[str, Any]]) -> Iterator[JobEnrichment]:
        """Classify a stream of postings, several per request where configured.

        A whole group counts as one failure for the circuit breaker: the thing
        being protected against is a provider that has stopped answering, and
        that is a property of the request, not of how many postings rode in it.
        """
        consecutive_failures = 0
        for group in _chunked(postings, self.postings_per_request):
            try:
                if len(group) == 1 and self.postings_per_request == 1:
                    yield self.classify(group[0])
                else:
                    yield from self.classify_batch(group)
                consecutive_failures = 0
            except ClassificationError as exc:
                log.warning("enrich.skip", count=len(group), error=str(exc))
                consecutive_failures += 1
            except Exception as exc:  # network / rate limit / unexpected
                log.error("enrich.error", count=len(group), error=str(exc))
                consecutive_failures += 1
            if consecutive_failures >= self.MAX_CONSECUTIVE_FAILURES:
                log.error("enrich.circuit_open", consecutive_failures=consecutive_failures)
                break

    def _to_enrichment(
        self, posting: dict[str, Any], result: LLMJobClassification, usage: Any
    ) -> JobEnrichment:
        return JobEnrichment(
            content_hash=posting["content_hash"],
            source=JobSource(posting["source"]),
            source_job_id=posting["source_job_id"],
            enriched_at=datetime.now(UTC),
            model=self.provider.model,
            prompt_version=self.prompt_version,
            schema_version=SCHEMA_VERSION,
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
            cost_usd=usage.cost_usd,
            normalized_role=result.normalized_role,
            role_family=result.role_family,
            seniority=result.seniority,
            employment_type=result.employment_type,
            remote_policy=result.remote_policy,
            technologies=result.technologies,
            visa=result.visa,
            requires_local_language=result.requires_local_language,
            working_languages=result.working_languages,
            english_sufficient=result.english_sufficient,
            relocation_support=result.relocation_support,
            enrichment_confidence=result.enrichment_confidence,
            raw_response=result.model_dump(mode="json"),
        )


def _chunked(items: Iterable[dict[str, Any]], size: int) -> Iterator[list[dict[str, Any]]]:
    """Fixed-size chunks. ``itertools.batched`` is 3.12+, this project is 3.11."""
    chunk: list[dict[str, Any]] = []
    for item in items:
        chunk.append(item)
        if len(chunk) >= size:
            yield chunk
            chunk = []
    if chunk:
        yield chunk


def _share_usage(usage: Any, count: int) -> Any:
    """Divide one request's usage across the postings it carried.

    Token counts and cost arrive per *request*. Attaching the full figure to
    every row would multiply the reported spend by the batch size, so each row
    carries its share and the totals stay additive.
    """
    if count <= 1:
        return usage

    def divide(value: float | int | None) -> Any:
        return None if value is None else value / count

    return LLMUsage(
        input_tokens=(None if usage.input_tokens is None else round(usage.input_tokens / count)),
        output_tokens=(None if usage.output_tokens is None else round(usage.output_tokens / count)),
        cost_usd=divide(usage.cost_usd),
    )
