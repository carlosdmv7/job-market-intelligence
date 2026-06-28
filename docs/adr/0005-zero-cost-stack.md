# ADR 0005 — Zero-cost stack: local LLM provider + free public job APIs

**Status:** accepted (supersedes the Scrapfly/Anthropic defaults in the original plan)

## Context
Hard constraint: 0€ to run. The original design assumed Scrapfly (paid) for
scraping and Claude Haiku (paid) for enrichment. Neither fits a no-budget setup.

## Decision
**Scraping:** drop Scrapfly from the default path. Ingest from free, public,
no-registration JSON APIs via plain `httpx` — Remotive, Arbeitnow, RemoteOK
(the `DEFAULT_SOURCES`). Scrapfly (LinkedIn/Indeed) and Adzuna (free key,
per-country NL/ES/DE search) remain registered as improvement-section hooks.

**LLM:** introduce a pluggable provider interface (`jmi_enrichment.providers`)
selected by `JMI_LLM_PROVIDER`. Default **Ollama** (local, no key, no rate
limits, no cost) running e.g. `qwen2.5:7b`/`gemma3`. Gemini free tier and
Anthropic are drop-in alternatives. Enrichment and the text-to-SQL agent both go
through this interface, so the whole product is 0€ out of the box.

## Consequences
- No anti-bot coverage for LinkedIn/Indeed by default — acceptable; the free
  APIs (remote + EU) match the relocation use case better.
- Ollama needs local RAM (~6–8 GB for a 7B model); on a server, switch to Gemini.
- Cost tracking (`cost_usd`) is 0 for local/free providers; the Anthropic path
  still computes real cost with cache multipliers.
- Adding sources changed `JobSource` → `SCHEMA_VERSION` 0.2.0.
