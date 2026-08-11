# Evals — the visa classifier's contract

Why this exists and what the labels mean:
[ADR 0006](../docs/adr/0006-llm-evaluation.md).

| File | What |
|---|---|
| `golden_set.jsonl` | ~200 sampled postings. `visa_status_true` is the hand label — the only field a human edits. |
| `fixtures/responses.jsonl` | Real production model outputs, replayed in CI so it needs no key, no quota and no network. |
| `thresholds.json` | The committed quality floor. CI fails below it. |
| `report.json` | Last scoring run. Read by the app's "How it works" page. |

## The loop

```bash
# 1. Sample (deterministic, stratified, additive — existing labels survive).
make evals-sample                      # or: --size 200 --dry-run to see the strata

# 2. Label by hand — keys 1-5, saves after every label.
make evals-label                       # or: LIMIT=25 for a short sitting
#    Postings that actually discuss the right to work come first, and the
#    vocabulary is highlighted. It shows you no suggested answer: the whole
#    point is that the label is yours. Editing the JSONL by hand still works.

# 3. Harvest the model outputs the pipeline already stored.
make evals-record

# 4. Score. Offline, deterministic, free.
make evals                             # add --check to enforce thresholds
```

After a prompt or model change, run `--provider live` to see what actually
moved, then re-record and commit the fixtures.

## Labelling guidance

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
