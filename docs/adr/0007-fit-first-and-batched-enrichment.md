# ADR 0007 — Stack fit is the product; visa sponsorship is a showcase

**Status:** Accepted
**Date:** 2026-09-13
**Amends:** [ADR 0003 — Visa as enum + confidence + evidence](0003-visa-enum-classification.md),
[ADR 0006 — The golden set is the contract](0006-llm-evaluation.md)

## Context

ADR 0003 opens with "visa sponsorship is the killer feature for a Spanish
profile relocating to the EU". Two facts, neither available when that was
written, say otherwise.

**The signal is not in the corpus.** Across the 730 postings the classifier had
read, its own output was `unclear` 583 times, `likely_no` 126, `explicit_no` 14,
`likely_yes` 6 — and `explicit_yes` **once**. The first 14 hand labels scored
precision 0.000 on `explicit_yes`. That is not a failing classifier; it is a
class with no support. No amount of further labelling changes it.

**The user does not need the feature.** A Spanish citizen has the right to work
anywhere in the EU. The flagship was useless to the only person using it.

Separately, the market data pointed at the wrong country. Of 867 open data roles,
Spain holds 244 and the Netherlands 169 — while the app, the landing page and the
README were all built around the Dutch corpus.

## Decision

**1. The product question is "which open data roles match my stack?"** The app is
organised around that: an Overview of what is open and in which stacks, a
stack-overlap CV ranking, and market comparison by country and technology.

**2. Visa sponsorship is demoted, not deleted.** `is_recognised_sponsor` remains
a column and a filter, and the Netherlands page remains as the clearest worked
example of the principle in ADR 0003 — that a fact with an authoritative source
should be looked up and shown with its receipt rather than inferred. It is
presented as engineering evidence, not as a daily tool, and it states on arrival
that an EU passport makes it irrelevant.

**3. The eval target is a parameter, defaulting to `english_sufficient`.** That
field splits roughly 355 / 330 / 45, which is measurable, and it decides
something: can someone who does not speak the local language do this job? The
visa target and its labels are kept and still scoreable with `--target visa`.

**4. A posting that left its board is marked closed.** Boards delete filled
roles rather than closing them, so days-since-last-seen is the only liveness
signal. 1,331 of 2,755 data roles had not been seen in 21+ days and were being
presented as current. `is_active` is measured against the corpus's newest
observation, never `current_date`, so a stalled pipeline cannot mark everything
closed on a calendar technicality.

**5. Enrichment batches ten postings per request.** The free-tier quota is
counted in requests — `GenerateRequestsPerDayPerProjectPerModel-FreeTier`,
`quotaValue 20`, named in the 429 body — not in tokens. One posting per request
spent the entire budget on round trips and left stack coverage at 12%. Responses
carry an echoed index and are matched by it, never by position, because a
reordered or short response would otherwise attach classifications to the wrong
jobs silently. Descriptions are stripped of HTML first: roughly half of a 10k
character posting is markup, so the truncation budget had been cutting inside the
company intro, before the requirements block.

## Consequences

Coverage of the field the product depends on goes from ~183 days of backlog to
under three weeks. The reported numbers change meaning: coverage is now measured
against open data roles rather than every row ever collected, which took the
headline figure from a misleading 8% to an honest 21%.

The eval's headline metric changes, so the visa thresholds in
`evals/thresholds.json` are frozen rather than enforced as a goal — kept as the
record of what was once asserted.

What this costs: the auditable-register work is no longer the first thing a
reader meets, and a reader who came specifically for relocation sponsorship has
to navigate to it. That is the right trade when the measured signal is one
positive in 730.

## Alternatives considered

**Keep labelling the visa golden set until the metric stabilises.** Rejected on
arithmetic: with one `explicit_yes` in 730 postings, reaching even ten positives
means labelling on the order of 7,000 postings by hand.

**Delete the visa feature entirely.** Rejected because it is the most auditable
component in the repo and it demonstrates the deterministic-versus-inferred
discipline better than anything else here. The objection was to its placement,
not its existence.

**Raise the enrichment cadence or the `--limit`.** Rejected: both were already
above the ceiling. The limit said 50 while the quota allowed 20, and the surplus
was being spent on retry backoff. Frequency was never the constraint.

**Run the model locally with Ollama.** Not available on the development machine:
the network does not reach the Cloudflare R2 host that serves Ollama's model
blobs, and Ollama sees only CPU under WSL2. Recorded so the option is re-tested
rather than re-argued.
