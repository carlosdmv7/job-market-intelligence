-- Cleaned pass over LLM enrichment. One row per content_hash.

with source as (
    select * from {{ source('raw', 'raw_job_enrichment') }}
)

select
    content_hash,
    source,
    source_job_id,
    enriched_at,
    model,
    prompt_version,
    schema_version,
    input_tokens,
    output_tokens,
    cost_usd,
    normalized_role,
    role_family,
    seniority,
    employment_type,
    remote_policy,
    technologies,
    visa_status,
    visa_confidence,
    visa_evidence,
    visa_reasoning,
    -- the killer flag, normalized once here for every downstream consumer
    visa_status in ('explicit_yes', 'likely_yes')          as is_visa_sponsor,
    requires_local_language,
    working_languages,
    english_sufficient,
    relocation_support,
    enrichment_confidence
from source
