{# Cross-source cluster key — the SQL counterpart of
   jmi_enrichment.dedup.canonical_key. Normalizes company + title + country,
   then hashes. Two postings of the same role/company/country from different
   sources collapse to the same canonical_job_id. #}
{% macro jmi_canonical_key(company, title, country) %}
    md5(
        concat_ws('|',
            {{ jmi_norm(company) }},
            {{ jmi_norm_title(title) }},
            lower(coalesce({{ country }}, ''))
        )
    )
{% endmacro %}

{# lowercase, strip non-alphanumerics, collapse whitespace #}
{% macro jmi_norm(col) %}
    trim(regexp_replace(
        regexp_replace(lower(coalesce({{ col }}, '')), '[^a-z0-9 ]', ' ', 'g'),
        '\s+', ' ', 'g'))
{% endmacro %}

{# like jmi_norm but also drops parentheticals, e.g. "(m/w/d)" #}
{% macro jmi_norm_title(col) %}
    trim(regexp_replace(
        regexp_replace(
            regexp_replace(lower(coalesce({{ col }}, '')), '\([^)]*\)', ' ', 'g'),
            '[^a-z0-9 ]', ' ', 'g'),
        '\s+', ' ', 'g'))
{% endmacro %}
