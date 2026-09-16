# ADR 0010 — Cross-check against a deterministic signal instead of hand labels

**Status:** Accepted
**Date:** 2026-09-16
**Amends:** [ADR 0007 §3](0007-fit-first-and-batched-enrichment.md) — the eval
target became a parameter defaulting to `english_sufficient`. It stays a
parameter; what changes is that the English target is deliberately never
labelled.

## Context

ADR 0007 moved the eval's headline target from visa sponsorship, which turned
out to have no signal in the corpus, to english-sufficiency, which splits close
to evenly and decides something real. The intent was to hand-label ~200 postings
and report an accuracy figure.

That labelling was never done, and on inspection it should not be. Three
observations, in order of weight.

**The app does not filter on the field.** The Find Jobs language filter runs on
`detected_language` — the language the advertisement is *written* in, detected
deterministically on ingest — not on the model's `english_sufficient`. That was
already the design (the deterministic signal is present on 811 of 811 open data
roles, where the model's read reaches only the share the daily quota has
covered). Scoring a field that nothing filters by buys a number, not a better
tool.

**The deterministic signal already validates the model, for free.** The
classifier is never shown the detected language, so the two are independent.
Lining them up costs one GROUP BY and covers every posting the model has read —
1,065 of them today, against the 30 a hand-labelled set would have needed weeks
to reach. Measured 2026-09-16:

| Ad written in | Postings read | Model says "English is enough" |
|---|---|---|
| English | 643 | 85% |
| Dutch | 255 | **0.4%** — one posting |
| Swedish | 72 | 10% |
| German | 64 | 9% |
| Spanish | 31 | 48% |

A model pattern-matching on "data engineer" would answer the same way whatever
language the ad was in. This separation has to come from reading the text.

**The decision the user actually makes does not need the model's answer.** The
rule in practice: *an ad in another language is certainly not for an
English speaker; an ad in English might be, and I will judge that one myself
from the posting.* The table above is exactly that rule, measured. The model's
reading is useful detail on a posting card and a poor thing to gate a filter on.

## Decision

**1. The English target is deliberately left unlabelled, and the app says so.**
Not "labelling is in progress" — that was a promise the page had been making
since ADR 0007 and it is not going to be kept. The How It Works page now states
that no headline accuracy is claimed, why, and what is shown instead.

**2. The cross-check is a first-class section of How It Works**, computed live
from the marts: detected language against the model's read, per language, with
the count the model declined to answer. It is labelled a **diagnostic, not an
accuracy score**, in the same terms the repo already uses for the IND-register
agreement — neither column is ground truth, so what it measures is whether two
independent signals tell the same story.

**3. Hand labels stay the instrument for questions a cross-check cannot reach.**
The harness keeps `--target`, the 22 visa labels stay scoreable, and the
sampler, replay and metrics code is unchanged. What changed is when that
instrument is worth its cost, not whether it exists.

**4. `evals/thresholds.json` records `english` as deliberately empty**, with the
reason, rather than as a placeholder waiting to be filled.

## Consequences

The project stops claiming an accuracy number it was never going to produce, and
gains a measurement over 1,065 postings instead of a hypothetical 30. CI's eval
job keeps replaying recorded responses and stays green while reporting rather
than gating, which is what it already did.

What this gives up is the cleanest possible portfolio line — "classifier
measured at N% accuracy against a hand-labelled golden set". What replaces it is
weaker as a headline and more defensible under questioning: a cross-check
against an independent signal at full coverage, plus a golden set whose one
completed measurement retired a feature. Anyone who asks "how do you know the
model is any good?" gets a real answer with a real limitation attached.

The cross-check inherits a genuine blind spot, stated on the page: a
Dutch-language ad can describe an English-speaking team, and roughly half the
Spanish-language postings the model read do claim English suffices. Language of
the ad is a strong proxy, not the truth. If that gap ever starts to matter —
if the user finds himself filtering out roles he could have done — the honest
fix is a small, targeted labelling run on exactly those cases, which is what the
harness is still there for.

## Alternatives considered

**Label 200 postings and publish the accuracy figure.** The original plan.
Rejected on cost against value: an afternoon per hundred rows, to score a field
the app does not filter on, while the free cross-check already covers five times
as many postings.

**Auto-label from `detected_language` and score against that.** Would have
produced an impressive-looking accuracy number in minutes. Rejected outright:
that is not ground truth, it is a second model's opinion, and scoring one signal
against another while calling the result "accuracy" is precisely the dishonesty
this project exists to argue against. Calling it agreement and reporting it as a
diagnostic is the same computation told truthfully.

**Drop the eval harness.** Rejected. It holds the visa measurement, it is wired
into CI offline, and the reason to keep a measuring instrument is not that you
are using it today.
