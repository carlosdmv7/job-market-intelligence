{# Company-name normalization for cross-referencing job postings against the IND
   recognised-sponsor register. Applied identically to both sides of the join.

   Mirrors jmi_scrapers.ind_sponsors.normalize_company:
     1. strip accents + lowercase
     2. drop legal forms (b.v. / n.v. / v.o.f. / c.v. / u.a. / b.a. / s.a. / s.r.l.)
     3. drop punctuation -> space
     4. drop noise tokens (holding / group / nederland / international / ...)
     5. collapse whitespace + trim
   e.g. "ASML Netherlands B.V." -> "asml", "Adyen N.V." -> "adyen". #}
{% macro jmi_normalize_company(col) %}
    trim(
        regexp_replace(
            regexp_replace(
                regexp_replace(
                    regexp_replace(
                        strip_accents(lower(coalesce({{ col }}, ''))),
                        '\b([bn][^a-z0-9]*v|v[^a-z0-9]*o[^a-z0-9]*f|c[^a-z0-9]*v|u[^a-z0-9]*a|b[^a-z0-9]*a|s[^a-z0-9]*a|s[^a-z0-9]*r[^a-z0-9]*l)\b', ' ', 'g'),
                    '[^a-z0-9 ]', ' ', 'g'),
                '\b(holding|holdings|group|groep|international|nederland|netherlands|the|and|inc|ltd|llc|gmbh|sa|company|co|corp|corporation|europe|global|bv|nv|vof|cv|ua|ba)\b', ' ', 'g'),
            '\s+', ' ', 'g')
    )
{% endmacro %}
