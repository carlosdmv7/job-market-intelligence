# Evals — the classifier's contract

Why this exists and what the labels mean:
[ADR 0006](../docs/adr/0006-llm-evaluation.md). Why the measured field changed:
[ADR 0007](../docs/adr/0007-fit-first-and-batched-enrichment.md).

**Two targets, one harness.** `--target english` is the default: *can someone
who does not speak the local language do this job?* `--target visa` is the
original, kept and still scoreable — its numbers are what retired that feature,
so they belong in the record rather than in the bin. A row can carry a label for
one target and not the other; that is normal, not incomplete.

| File | What |
|---|---|
| `golden_set.jsonl` | ~200 sampled postings. `english_sufficient_true` and `visa_status_true` are the hand labels — the only fields a human edits (plus `notes`). |
| `fixtures/responses.jsonl` | Real production model outputs, replayed in CI so it needs no key, no quota and no network. |
| `thresholds.json` | The committed quality floor. CI fails below it. |
| `report.json` | Last scoring run. Read by the app's "How it works" page. |

## The loop

```bash
# 1. Sample (deterministic, stratified, additive — existing labels survive).
make evals-sample                      # or: --size 200 --dry-run to see the strata

# 2. Label by hand — keys 1-5, saves after every label.
make evals-label TARGET=english        # or: LIMIT=25 for a short sitting
#    Postings that actually discuss the right to work come first, and the
#    vocabulary is highlighted. It shows you no suggested answer: the whole
#    point is that the label is yours. Editing the JSONL by hand still works.

# 3. Harvest the model outputs the pipeline already stored.
make evals-record

# 4. Score. Offline, deterministic, free.
make evals TARGET=english              # enforces the committed thresholds
```

After a prompt or model change, run `--provider live` to see what actually
moved, then re-record and commit the fixtures.

## Labelling guidance — `english` (the default target)

The question is **"could someone who speaks English but not the local language
do this job?"**, judged only from the posting's text.

- `yes` — the text says the working language is English, or the ad is in
  English and names no local-language requirement.
- `no` — the local language is a requirement of the work, not a nice-to-have
  ("Dutch at C1 for client contact", an ad written entirely in Swedish for a
  role serving Swedish customers).
- `unclear` — the text does not say. An honest and frequent answer; it is a
  class of its own precisely so silence is never scored as "no".

## Labelling guidance — `visa` (kept, no longer the headline)

The question is **"does this posting's text state or imply that the employer
will sponsor a work permit?"** — not "can this employer sponsor?". The second
question is already answered, better, by the deterministic IND register join.
Mixing them corrupts the labels.

- `explicit_yes` — the text offers sponsorship or relocation for non-EU hires.
- `likely_yes` — strong implicit signals ("open to candidates worldwide", "we
  help you relocate") without an explicit sponsorship statement.
- `unclear` — the text says nothing either way. This is the honest majority.
- `likely_no` — implicit signals against: local language mandatory, cleared
  government work, "must already have EU work authorization" with no offer to
  sponsor.
- `explicit_no` — the text rules it out ("we do not sponsor visas").

Put anything ambiguous in `notes`. A label you had to argue with yourself about
is exactly the one a future you will want the reasoning for.
