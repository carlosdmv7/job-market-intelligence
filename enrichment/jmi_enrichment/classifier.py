"""Provider-agnostic classifier: posting row -> JobEnrichment.

Wraps an :class:`~jmi_enrichment.providers.LLMProvider` (Ollama by default).
The provider returns a validated :class:`LLMJobClassification` + usage; this
class adds lineage/cost metadata and builds the full ``JobEnrichment``.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from jmi_core import SCHEMA_VERSION
from jmi_core.logging import get_logger
from jmi_core.schema import JobEnrichment, JobSource

from jmi_enrichment.models import LLMJobClassification
from jmi_enrichment.prompts import SYSTEM_PROMPT, build_user_prompt, json_output_instructions
from jmi_enrichment.providers import ClassificationError, LLMProvider, get_provider

if TYPE_CHECKING:
    from collections.abc import Iterable, Iterator

    from jmi_core.settings import Settings

log = get_logger(__name__)


class JobClassifier:
    def __init__(self, settings: Settings, *, provider: LLMProvider | None = None):
        self.settings = settings
        self.provider = provider or get_provider(settings)
        self.prompt_version = settings.enrichment_prompt_version

    def classify(self, posting: dict[str, Any]) -> JobEnrichment:
        user = build_user_prompt(posting) + "\n\n" + json_output_instructions()
        result, usage = self.provider.classify(
            system=SYSTEM_PROMPT, user=user, schema=LLMJobClassification
        )
        return self._to_enrichment(posting, result, usage)

    def classify_many(self, postings: Iterable[dict[str, Any]]) -> Iterator[JobEnrichment]:
        for posting in postings:
            try:
                yield self.classify(posting)
            except ClassificationError as exc:
                log.warning("enrich.skip", content_hash=posting.get("content_hash"), error=str(exc))
            except Exception as exc:  # network / rate limit / unexpected
                log.error("enrich.error", content_hash=posting.get("content_hash"), error=str(exc))

    def _to_enrichment(
        self, posting: dict[str, Any], result: LLMJobClassification, usage: Any
    ) -> JobEnrichment:
        return JobEnrichment(
            content_hash=posting["content_hash"],
            source=JobSource(posting["source"]),
            source_job_id=posting["source_job_id"],
            enriched_at=datetime.now(timezone.utc),
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
