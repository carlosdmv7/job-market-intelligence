"""Prompts for the enrichment classifier.

The system prompt is stable (taxonomy + rubric) so it caches across calls; the
per-posting content goes in the user turn. Bumping the taxonomy is a
``JMI_ENRICHMENT_PROMPT_VERSION`` change (forces re-enrichment downstream).
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from jmi_core.schema import (
    EmploymentType,
    RemotePolicy,
    Seniority,
    VisaSponsorshipStatus,
)
from jmi_core.text import strip_html

#: Truncate very long descriptions to keep cost and latency predictable.
#:
#: Counted in characters of *plain text*, not markup. Descriptions arrive as raw
#: HTML — a typical 10k-character posting is about half tags, and one board sends
#: `<p style="min-height:1.5em">` before every paragraph. Sending that spent
#: roughly half the budget on markup and pushed the requirements block, where the
#: tech stack actually lives, past the cut. Stripping first is what makes a
#: truncation limit mean anything.
MAX_DESCRIPTION_CHARS = 6000

#: Batched requests truncate harder. Ten postings at the single-call budget is a
#: 60k-character prompt, and a model given that much text starts losing track of
#: which posting it is on — the failure the response indexing is designed to
#: catch, but better avoided than caught. 3k characters of stripped text reaches
#: well into the requirements block; 3k characters of HTML did not get past the
#: company intro, which is why the first batched run returned no technologies at
#: all.
MAX_BATCH_DESCRIPTION_CHARS = 3000

SYSTEM_PROMPT = """\
You classify software/data job postings for a job-market intelligence tool.
The end user is a Spanish data professional evaluating relocation to the
Netherlands or elsewhere in the EU, so visa sponsorship and language
requirements are the highest-value signals.

Postings may be in English, Spanish, Dutch, German, or Portuguese. Read the
original language directly — do NOT translate. Base every judgement only on the
text provided; never invent facts.

Return values from these controlled vocabularies:

- seniority: intern | junior | mid | senior | lead | principal | manager | unknown
- employment_type: full_time | part_time | contract | freelance | internship | temporary | unknown
- remote_policy: onsite | hybrid | remote | remote_country_restricted | unknown
  (use remote_country_restricted when remote is offered only from specific countries/regions)

visa.status — the killer signal. Choose the strongest supported option:
- explicit_yes : the posting explicitly offers visa sponsorship and/or relocation for non-EU/non-local candidates.
- likely_yes   : strong implicit signals (international team, "open to candidates worldwide", "we help you relocate") but no explicit sponsorship statement.
- unclear      : no signal either way.
- likely_no    : implicit signals against (local-language mandatory, government/defense/clearance, "must already have EU work authorization" without offering to sponsor).
- explicit_no  : the posting explicitly states no sponsorship (e.g. "we do not sponsor visas", "must have existing right to work").

For visa.evidence, quote the VERBATIM snippet (original language) that justifies
the status, or null if status is "unclear". Keep visa.reasoning to one sentence.
visa.confidence and enrichment_confidence are 0.0-1.0.

Language fields, judged for someone who speaks Spanish + English but not the
local language:
- requires_local_language: true if a non-English local language (Dutch, German,
  Portuguese, ...) is required to perform the job (not merely "a plus").
- working_languages: ISO 639-1 codes actually required/used (e.g. ["en"], ["nl","en"]).
- english_sufficient: true if English alone is enough to do the job.
- relocation_support: true only if relocation help is mentioned (separate from visa).

technologies: normalized, lowercased, deduplicated tech/tools/skills actually
named in the posting (e.g. ["python","dbt","snowflake","airflow"]). Omit soft skills.

normalized_role: a clean canonical title (e.g. "Analytics Engineer", "Data
Engineer", "ML Engineer"). role_family: the broad family.

When the text is genuinely silent on a field, use the unknown/null option and a
low confidence rather than guessing."""


def _readable(posting: dict[str, Any], budget: int) -> str:
    """The posting's description as plain text, truncated to ``budget`` chars."""
    description = strip_html(posting.get("description_raw")) or ""
    if len(description) > budget:
        return description[:budget] + " …[truncated]"
    return description


def build_user_prompt(posting: dict[str, Any]) -> str:
    """Render one posting (a warehouse row dict) into the user message."""
    description = _readable(posting, MAX_DESCRIPTION_CHARS)

    lines = [
        f"Title: {posting.get('title') or '(none)'}",
        f"Company: {posting.get('company_name') or '(unknown)'}",
        f"Location: {posting.get('location_raw') or '(unknown)'}",
        f"Country: {posting.get('country_code') or '(unknown)'}",
        f"Detected language: {posting.get('detected_language') or '(unknown)'}",
        f"Salary (raw): {posting.get('salary_raw') or '(none)'}",
        "",
        "Job description:",
        description or "(no description provided)",
    ]
    return "\n".join(lines)


def _vals(enum_cls: type[StrEnum]) -> str:
    return "|".join(e.value for e in enum_cls)


def classification_keys() -> str:
    """The key-by-key shape of one classification object.

    Split out from :func:`json_output_instructions` so a batched request can
    quote the same field list without also repeating "respond with ONLY a JSON
    object" in the middle of a different envelope's instructions.

    Enum value lists are generated from the schema so they never drift.
    """
    return (
        "normalized_role (string|null), role_family (string|null),\n"
        f"seniority (one of: {_vals(Seniority)}),\n"
        f"employment_type (one of: {_vals(EmploymentType)}),\n"
        f"remote_policy (one of: {_vals(RemotePolicy)}),\n"
        "technologies (array of lowercase strings),\n"
        "visa (object with: "
        f"status one of: {_vals(VisaSponsorshipStatus)}; "
        "confidence number 0..1; evidence string|null; reasoning string|null),\n"
        "requires_local_language (boolean|null), working_languages (array of ISO 639-1 strings|null),\n"
        "english_sufficient (boolean|null), relocation_support (boolean|null),\n"
        "enrichment_confidence (number 0..1|null)"
    )


def json_output_instructions() -> str:
    """Exact JSON shape for a single-posting request, appended to the user turn.

    Anthropic's native structured output ignores this; it's harmless there.
    """
    return (
        "Respond with ONLY a JSON object (no markdown, no commentary) with "
        "exactly these keys:\n" + classification_keys()
    )


def build_batch_user_prompt(postings: list[dict[str, Any]]) -> str:
    """Render several postings into one user message, explicitly numbered."""
    blocks = []
    for i, posting in enumerate(postings, start=1):
        description = _readable(posting, MAX_BATCH_DESCRIPTION_CHARS)
        blocks.append(
            "\n".join(
                [
                    f"===== POSTING {i} =====",
                    f"Title: {posting.get('title') or '(none)'}",
                    f"Company: {posting.get('company_name') or '(unknown)'}",
                    f"Location: {posting.get('location_raw') or '(unknown)'}",
                    f"Country: {posting.get('country_code') or '(unknown)'}",
                    f"Detected language: {posting.get('detected_language') or '(unknown)'}",
                    f"Salary (raw): {posting.get('salary_raw') or '(none)'}",
                    "",
                    "Job description:",
                    description or "(no description provided)",
                ]
            )
        )
    return "\n\n".join(blocks)


def batch_json_output_instructions(count: int) -> str:
    """JSON shape for a batched request: one indexed entry per posting."""
    return (
        f"There are {count} postings above, numbered 1 to {count}.\n"
        "Respond with ONLY a JSON object (no markdown, no commentary):\n"
        '{"results": [{"index": <the posting number>, "classification": {...}}, ...]}\n'
        f"Return exactly {count} entries, one per posting, each with the index of the "
        "posting it describes. Classify each posting independently — do not let one "
        "posting's requirements leak into another's.\n\n"
        "Each `classification` object has exactly these keys:\n" + classification_keys()
    )
