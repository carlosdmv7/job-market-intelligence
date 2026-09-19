# ADR 0011 — Market Detail absorbs the visa page, and states what it cannot see

**Status:** Accepted
**Date:** 2026-09-19
**Amends:** [ADR 0007 §2](0007-fit-first-and-batched-enrichment.md) — visa
sponsorship was demoted from product to showcase, and the Netherlands page was
kept as a standalone entry in the navigation. It is no longer standalone.

## Context

ADR 0007 demoted the visa feature but left its page in the top navigation as
**🛂 Visa Signal (NL)**, filed under the engineering pages. The reasoning was
that it reads as evidence rather than as a product surface.

It doesn't. Two months of use produced the plain reader's verdict from the
person who owns the project: *"sigues habiéndome dejado lo de la visa
sponsorship de Netherlands… así no parece que está muy centrado a Netherlands
o qué?"* — and, more damningly, *"es que no entiendo muy bien el objetivo"*.
When the author cannot state what a page is for, no visitor will work it out.

Measured, the surface was larger than the demotion implied:

- The navigation carried a passport emoji and the string "(NL)" — a five-market
  app advertising one country's immigration process.
- **Find Jobs**, the page used daily, carried two of its nine controls for it:
  an "IND sponsor only" toggle (1 of 5 toggles) and a "Visa signal" sort option
  (1 of 4). Both answer a question an EU passport already answers.

Separately, and discovered while building the replacement, the per-country
picture had a hole in it big enough to invalidate a chart. Average description
length and technologies extracted, by source:

| Source | Avg. characters | Avg. technologies found |
|---|---|---|
| arbeitnow | 7,840 | 4.2 |
| jobtech (SE) | 4,046 | 7.9 |
| **adzuna (ES · DE · NL)** | **500** | **1.0** |

Adzuna returns a teaser, not a job description. So "Sweden asks for dbt more
than Spain does" is an artifact of what the boards publish, and 91% of Swedish
roles are stack-matchable against 30–39% of Dutch, German and Spanish ones —
which is also the real reason My Fit can rank only 363 of 767 open roles.

## Decision

**1. The Netherlands visa page becomes a section of a per-market page.** The
new **Market Detail** page takes a market and reports what is open, what it asks
for, who is hiring, and how legible it is. The IND cross-reference — sponsor
rates, KvK receipts, the per-posting evidence card — renders only when the
Netherlands is selected, because that is precisely what it is: the one tracked
market that publishes a machine-readable register. Nothing about it was
deleted.

**2. It moves from "How it works" to "Analyse", as 🌍 Market Detail.** It is a
product page now, and it answers a question the app could not previously
answer: *should I concentrate my search on Spain or on Germany?*

**3. The two visa controls leave Find Jobs.** The sort option is replaced by
"Stack read", and the "IND sponsor only" toggle is gone; "LLM-read only" becomes
"Stack read only", which is the distinction that actually matters now that
enrichment coverage has reached 100% of open roles but *extraction* has not.

**4. Legibility is a headline metric, not a footnote.** "Roles we can
stack-match" sits in the KPI row of every market, and a table underneath gives
the source, its average description length and the technologies extracted from
it. The stack chart carries an explicit warning against cross-market
comparison.

## Consequences

The navigation no longer implies a Dutch relocation tool, and the most auditable
component in the repo survives intact, in the one place where it is obviously
relevant. A reader who selects the Netherlands still gets the KvK receipts and
the 34%-vs-3% finding.

The app also now admits, per market, how much of that market it can actually
read — which is uncomfortable (Spain, the largest market, is 39% legible) and is
the honest version of a number that was previously implied to be a market fact.

What this costs: the visa work is now two clicks deep and a reader skimming the
navigation will not find it. For a feature the author does not need and the
corpus barely supports, that is the correct depth. The README and the portfolio
brief still name it, for anyone reading the project rather than using it.

A fan-out bug was found and fixed while building this: joining
`staging.stg_job_postings` (observation grain — one row per sighting) to the
marts multiplied the posting count by how long each ad had been on the board,
rendering Spain's 229 open roles as 5,160 and weighting the averages toward
whatever had been listed longest.

## Alternatives considered

**Delete the visa feature entirely**, along with the IND scraper, the seed, the
dbt columns and the ADRs describing them. Genuinely considered, and the author
offered it. Rejected: the register cross-reference is the clearest demonstration
in the repo of the principle the whole project argues for — a fact with an
authoritative source is looked up, not inferred — and it produced a measured
finding (3% of remote-board employers can sponsor, against 34% of Dutch local
ones) that no model reading job text could reach. The objection was to its
placement, again, not to its existence.

**Rename the page and leave it standalone.** Cheaper, and it would have fixed
the navigation. Rejected because it leaves the author's real objection
unanswered: he could not say what the page was *for*. A page named after a
principle is still a page with no job. Giving it the job — "tell me about this
market" — is what makes the visa section make sense inside it.

**Fix the Adzuna truncation instead of documenting it.** The full text would
mean fetching each posting's own page: anti-bot exposure, rate limits, and a
much slower ingest, for a source that already gives title, company, location,
salary and country. Recorded as a known limit and surfaced in the app, which is
the same treatment every other coverage gap in this project gets.
