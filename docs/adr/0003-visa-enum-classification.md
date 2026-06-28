# ADR 0003 — Visa sponsorship as an enum + confidence + evidence

**Status:** accepted

## Context
Visa sponsorship is the killer feature for a Spanish profile relocating to the
EU. A boolean throws away signal: "no sponsorship" is a strong *negative* filter,
distinct from "unclear".

## Decision
Model visa as a value object: `status ∈ {explicit_yes, likely_yes, unclear,
likely_no, explicit_no}` + `confidence` (0–1) + verbatim `evidence` snippet +
one-sentence `reasoning`. The classifier also captures relocation-fit fields
(`requires_local_language`, `working_languages`, `english_sufficient`,
`relocation_support`) because "English-only, sponsors, helps relocate" is the
real query. `is_visa_sponsor` (= status in explicit_yes/likely_yes) is
materialized once in staging for every downstream consumer.

## Consequences
- Findings are rankable by certainty and auditable (evidence shown in the app).
- The enum is part of the contract; changing members is a `SCHEMA_VERSION` bump
  and a dbt `accepted_values` update.
