"""Provider tests: JSON extraction + Ollama parsing (mocked httpx)."""

from __future__ import annotations

import json

import httpx
import pytest

from jmi_core.schema import VisaSponsorshipStatus
from jmi_core.settings import Settings
from jmi_enrichment.models import LLMJobClassification
from jmi_enrichment.providers import (
    AnthropicProvider,
    ClassificationError,
    GeminiProvider,
    OllamaProvider,
    extract_json,
    get_provider,
)

VALID_JSON = json.dumps(
    {
        "normalized_role": "Data Engineer",
        "role_family": "Data Engineering",
        "seniority": "mid",
        "employment_type": "full_time",
        "remote_policy": "remote",
        "technologies": ["dbt", "snowflake"],
        "visa": {
            "status": "explicit_yes",
            "confidence": 0.9,
            "evidence": "we sponsor",
            "reasoning": None,
        },
        "requires_local_language": False,
        "working_languages": ["en"],
        "english_sufficient": True,
        "relocation_support": True,
        "enrichment_confidence": 0.88,
    }
)


def test_extract_json_plain_and_fenced():
    assert extract_json('{"a": 1}') == '{"a": 1}'
    assert extract_json('```json\n{"a": 1}\n```') == '{"a": 1}'
    assert extract_json('Here you go: {"a": 1} done') == '{"a": 1}'
    with pytest.raises(ClassificationError):
        extract_json("no json here")


def test_ollama_provider_parses(monkeypatch):
    class FakeResp:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "message": {"content": VALID_JSON},
                "prompt_eval_count": 250,
                "eval_count": 90,
            }

    captured = {}

    def fake_post(url, json=None, timeout=None):
        captured["url"] = url
        captured["json"] = json
        return FakeResp()

    monkeypatch.setattr(httpx, "post", fake_post)

    provider = OllamaProvider("qwen2.5:7b")
    result, usage = provider.classify(system="sys", user="usr", schema=LLMJobClassification)

    assert result.visa.status is VisaSponsorshipStatus.EXPLICIT_YES
    assert result.technologies == ["dbt", "snowflake"]
    assert usage.input_tokens == 250
    assert usage.output_tokens == 90
    assert usage.cost_usd == 0.0
    assert captured["url"].endswith("/api/chat")
    assert captured["json"]["format"] == "json"


def test_ollama_provider_raises_on_bad_json(monkeypatch):
    class FakeResp:
        def raise_for_status(self):
            return None

        def json(self):
            return {"message": {"content": "not json"}}

    monkeypatch.setattr(httpx, "post", lambda *a, **k: FakeResp())
    with pytest.raises(ClassificationError):
        OllamaProvider("m").classify(system="s", user="u", schema=LLMJobClassification)


def test_get_provider_selection():
    assert isinstance(get_provider(Settings(llm_provider="ollama")), OllamaProvider)
    assert isinstance(
        get_provider(Settings(llm_provider="gemini", gemini_api_key="k")), GeminiProvider
    )
    assert isinstance(get_provider(Settings(llm_provider="anthropic")), AnthropicProvider)
    with pytest.raises(ValueError):
        get_provider(Settings(llm_provider="bogus"))


def test_gemini_requires_key():
    with pytest.raises(ClassificationError):
        GeminiProvider("gemini-2.0-flash", api_key=None)
