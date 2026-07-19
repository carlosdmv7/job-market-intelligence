-- Current-state fact: one row per deduplicated canonical posting, joined to its
-- LLM enrichment. The analytical heart of the app + the text-to-SQL agent.

with postings as (
    select * from {{ ref('int_job_postings_deduplicated') }}
),

enrichment as (
    select * from {{ ref('stg_job_enrichment') }}
),

sponsors as (
    select * from {{ ref('stg_recognised_sponsors') }}
)

select
    p.canonical_job_id                                              as job_posting_key,
    p.canonical_job_id,
    p.content_hash,

    -- dimension foreign keys
    {{ dbt_utils.generate_surrogate_key(['p.company_name', 'p.country_code']) }} as company_key,
    {{ dbt_utils.generate_surrogate_key(['p.source']) }}           as source_key,
    cast(p.posted_at as date)                                      as posted_date_key,

    -- degenerate / descriptive
    p.source,
    p.source_job_id,
    p.source_url,
    p.apply_url,
    p.title,
    p.company_name,
    p.country_code,
    p.location_raw,
    p.is_remote_raw,
    p.cluster_size                                                 as source_count,
    p.posted_at,
    p.valid_through,
    p.salary_raw,
    p.scraped_at                                                   as last_seen_at,

    -- enrichment (normalized)
    e.normalized_role,
    e.role_family,
    e.seniority,
    e.employment_type,
    e.remote_policy,
    e.technologies,

    -- killer feature: LLM visa read (from the posting text)
    e.visa_status,
    e.visa_confidence,
    e.visa_evidence,
    e.visa_reasoning,
    coalesce(e.is_visa_sponsor, false)                            as is_visa_sponsor,
    e.requires_local_language,
    e.working_languages,
    e.english_sufficient,
    e.relocation_support,
    e.enrichment_confidence,
    (e.content_hash is not null)                                  as is_enriched,

    -- enrichment provenance: which model/prompt produced the read, and when —
    -- the app's detail view shows this so every LLM claim is attributable
    e.model                                                       as enrichment_model,
    e.prompt_version                                              as enrichment_prompt_version,
    e.enriched_at,

    -- killer feature: deterministic IND recognised-sponsor cross-reference
    -- (the company is legally authorised to sponsor a NL work visa)
    (s.company_norm is not null)                                  as is_recognised_sponsor,
    s.kvk_number                                                  as sponsor_kvk
from postings p
left join enrichment e on p.content_hash = e.content_hash
left join sponsors s on {{ jmi_normalize_company('p.company_name') }} = s.company_norm
