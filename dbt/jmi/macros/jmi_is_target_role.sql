{# Is this posting's title a data/analytics/ML role?

   Mirrors jmi_scrapers.free_apis.is_target_role / TARGET_ROLE_PATTERN, the
   same way jmi_normalize_company mirrors its Python counterpart. The scrapers
   now apply it at ingest time, but postings never age out of the marts — so
   without this the ~7,900 off-role rows already landed would stay visible
   forever, and the filter would only help months from now.

   Kept as a flag rather than a filter on purpose. The rows stay queryable:
   trends and "what does this board actually publish" are legitimate questions
   about the whole corpus, and silently deleting history to tidy a list is how
   a warehouse starts lying. The app decides where to apply it.

   Every term is anchored on both sides. An early Python version anchored only
   the front and matched "BI" inside "Bildung"; the mirror keeps that fix, and
   removes "bi-lingual" before matching as the Python side does (RE2 has no
   lookahead to exclude it in the pattern itself).
   tests/test_target_role_parity.py asserts both sides agree on real titles. #}
{% macro jmi_is_target_role(col) %}
    regexp_matches(
        regexp_replace(lower(coalesce({{ col }}, '')), '\bbi[\s-]+lingual\b', ' ', 'g'),
        '\b(data|analytics?|machine\s+learning|ml\s*ops|ml\s+engineer|ml|ai\s+engineer|ai\s*/\s*ml|business\s+intelligence|bi|etl|dbt|data\s*warehouse|datawarehouse|big\s*data|llm)\b'
    )
{% endmacro %}
