"""LLM enrichment (pluggable providers), salary parsing, and dedup recipes."""

from __future__ import annotations

from jmi_enrichment.classifier import JobClassifier
from jmi_enrichment.dedup import canonical_key, cosine_similarity, normalize_title
from jmi_enrichment.models import LLMJobClassification
from jmi_enrichment.providers import (
    AnthropicProvider,
    ClassificationError,
    GeminiProvider,
    LLMProvider,
    LLMUsage,
    OllamaProvider,
    get_provider,
)
from jmi_enrichment.salary import parse_salary

__all__ = [
    "JobClassifier",
    "LLMJobClassification",
    "LLMProvider",
    "LLMUsage",
    "OllamaProvider",
    "GeminiProvider",
    "AnthropicProvider",
    "get_provider",
    "ClassificationError",
    "parse_salary",
    "canonical_key",
    "normalize_title",
    "cosine_similarity",
]
