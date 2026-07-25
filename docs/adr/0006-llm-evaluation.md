# ADR 0006 — The golden set is the contract for the visa classifier

**Status:** Accepted
**Date:** 2026-07-25
**Supersedes/extends:** [ADR 0003 — Visa as enum + confidence + evidence](0003-visa-enum-classification.md)

## Context

ADR 0003 made the classifier's output *structured*: a closed enum, a confidence
and a verbatim evidence span. That made the output auditable one posting at a
time. It said nothing about whether the classifier is any **good**.

Until now the honest answer to "how accurate is the visa classification?" was
"nobody has measured it." That is the normal state of LLM features, and it is
the difference between *using* an LLM and *operating* one. Three concrete
problems followed from it:

1. **A prompt change was unfalsifiable.** Editing the rubric in
   `jmi_enrichment/prompts.py` could improve `explicit_no` recall and quietly
   destroy `explicit_yes` precision, and nothing in the repo would notice.
2. **A provider swap was a leap of faith.** `JMI_LLM_PROVIDER` moves between
   Ollama, Gemini and Anthropic. Those models do not agree, and the app
   presents their output identically.
3. **A real defect was invisible.** On the current corpus the classifier has
   produced **zero** `explicit_yes` across every enriched posting. That is
   either a true property of the corpus (only ~3% of postings mention permits
   at all) or a recall failure in the rubric. Without a labelled set, the two
   are indistinguishable — and they call for opposite responses.

## Decision

**A hand-labelled golden set of ~200 postings, committed to the repository, is
the contract the classifier is measured against.** Not the prompt, not the
model, not a vibe check on a few examples — the labelled file.

Concretely:

- **`evals/golden_set.jsonl`** holds one record per posting: identifiers, the
  deterministic IND signal, what production predicted when the row was sampled,
  a human `visa_status_true`, free-text notes, and the **exact rendered prompt
  input** the label was made against, pinned by `text_sha256`.
- **Sampling is a committed script** (`jmi_evals.sample`), deterministic and
  stratified by (market × register match), deliberately over-weighting the ~3%
  of postings that mention the right to work. A proportional sample of this
  corpus would be almost entirely `unclear` and would measure nothing.
- **Scoring is macro-averaged** over classes present in the truth. The rare
  classes are exactly the valuable ones; a micro average would let the
  `unclear` majority hide total failure on `explicit_yes`/`explicit_no`.
- **CI replays recorded responses** (`jmi_evals.replay`) harvested from
  `raw.raw_job_enrichment`, where the pipeline already stores every validated
  model output. No API key, no quota, no network, no variance in CI.
- **`evals/thresholds.json` is the committed floor.** CI fails below it.
  Raising a threshold requires a commit showing the measured improvement;
  lowering one is a deliberate, reviewable act rather than a silent drift.

### The label is the text's claim, not the truth about the employer

The ground truth answers **"does this posting's text state or imply
sponsorship?"** — never "can this employer sponsor?". The second question is
already answered, deterministically and better, by the IND register join.
Conflating them would corrupt the labels and quietly turn the eval into a test
of the register.

This is why the harness reports **agreement** between the two signals as a
*diagnostic and never as a score*. A recognised sponsor whose ad simply does
not discuss visas is the ordinary case and is precisely why the deterministic
signal is primary. The number worth watching is the reverse:
`llm_positive_confirmed_by_register` — the LLM asserting sponsorship at an
employer that legally cannot sponsor. That is a real failure mode, and it now
has a number.

## Consequences

**Good**

- Prompt and model changes become measurable. `--provider live` shows what
  moved; the fixtures are then re-recorded and committed.
- The zero-`explicit_yes` question becomes answerable rather than arguable.
- The app can state its own classifier's accuracy on the "How it works" page,
  which is a stronger claim than any description of the prompt.

**Costs, accepted**

- **Labelling is manual and does not scale.** ~200 postings is a few hours of
  reading. It is deliberately not LLM-assisted: a model labelling its own
  homework produces agreement, not truth.
- **The labelled set ages.** It reflects the corpus at sampling time. The
  sampler is additive (existing labels are preserved, new rows appended) so the
  set grows with the corpus instead of being redrawn.
- **The CI subset is smaller than the golden set.** Only postings the pipeline
  has already enriched have a recorded response — 17 of 200 at the time of
  writing, growing daily as the free-tier quota allows. Until the golden set is
  labelled, the eval job prints "nothing to score" and stays green: "nobody has
  labelled anything yet" and "the classifier got worse" are different events
  and CI must not report them the same way.

## Alternatives considered

- **LLM-as-judge.** Cheap, scales, and measures whether two models share a
  bias. Rejected as the *primary* contract; it is defensible as a later
  pre-filter to triage which postings a human should read.
- **Use the IND register as ground truth.** Free and already in the warehouse,
  but it answers a different question (see above). Using it would score the
  classifier on a task it is not performing.
- **scikit-learn for the metrics.** ~100 lines of arithmetic are not worth the
  largest dependency in a project whose selling point is that it runs at 0€.
  Hand-writing them also makes the averaging convention visible and testable.
