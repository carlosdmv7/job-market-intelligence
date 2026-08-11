# Contributing

Written down because it was already the practice and nothing enforced it — and
because one large branch had already mixed two unrelated bodies of work before
anyone noticed.

## Branches

One topic per branch, cut from an up-to-date `main`:

```bash
git switch main && git pull
git switch -c feat/visa-audit-filters
```

| Prefix | For |
|---|---|
| `feat/` | new behaviour |
| `fix/` | a defect in existing behaviour |
| `refactor/` | same behaviour, better shape |
| `docs/` | documentation, ADRs, README |
| `ci/` | workflows, tooling, build |
| `chore/` | housekeeping with no behaviour change |

If a branch starts needing "and also", that is a second branch. A reviewer who
has to hold two unrelated changes in their head reviews neither properly.

## Commits

[Conventional Commits](https://www.conventionalcommits.org/), enforced by a
`commit-msg` hook:

```
<type>(<scope>): <summary in the imperative, lower case, no full stop>

Why this change exists. What was wrong before, what is true now, and any
trade-off a future reader would otherwise have to reconstruct.
```

Types: `feat`, `fix`, `refactor`, `docs`, `ci`, `chore`, `test`, `perf`, `build`.
Scope is optional and names the area — `app`, `evals`, `flows`, `dbt`,
`scrapers`, `adr`.

```
feat(evals): keyboard labelling pass over the golden set
fix(app): last-ingest metric crashed the home page's live snapshot
ci: run the 45 dbt tests instead of only parsing the project
```

**The body carries the reasoning.** The diff already says what changed; the
message is where "why" survives. A message that only restates the diff is the
one you will curse in six months.

## Before pushing

```bash
make check        # ruff + mypy + pytest, exactly what CI runs
```

CI additionally builds the dbt project against a throwaway local DuckDB and
replays the LLM evals offline. Neither needs a secret, so both run on every
pull request.

## Pull requests

Open one per branch, even when working alone — the PR is where the reasoning
becomes reviewable, and `main` stays a series of deliberate merges rather than
a stream of half-finished states.

Merge with a **merge commit**. The individual commits are written to be read;
squashing throws away exactly the history this convention exists to produce.
Delete the branch after merging.

## Decisions

Anything that constrains future work — a schema, a dependency, a stack choice,
a measurement contract — gets an ADR in [`docs/adr/`](docs/adr). Number it
sequentially, state the alternatives you rejected and why. The rejected options
are the part you will want later, when someone proposes one of them again.
