# ADR 0008 — Gemini is the default provider; the container scaffolding is gone

**Status:** Accepted
**Date:** 2026-09-15
**Amends:** [ADR 0005 — Zero-cost stack](0005-zero-cost-stack.md)

## Context

ADR 0005 chose **Ollama** as the default LLM provider: local, no key, no quota,
no dependence on anyone's free tier. The reasoning was sound and the provider
interface it produced is what makes this decision a one-line change.

The default itself was wrong, and had been wrong in practice for a while before
anyone changed it. This code runs in exactly three places:

| Where | Can it run a local 7B model? |
|---|---|
| The development laptop (WSL2) | No — CPU only, and the network does not reach the R2 host serving Ollama's model blobs (ADR 0007) |
| The GitHub Actions runner that runs the daily pipeline | No — and it already sets `JMI_LLM_PROVIDER=gemini` explicitly |
| Streamlit Community Cloud, where the app is deployed | No — nothing like the RAM |

So `JMI_LLM_PROVIDER` defaulted to a provider that works in none of them. Every
surface that runs the LLM had to override it, and one that didn't — the app's
"Ask the Data" and "My Fit" pages, which print the live provider and then call
it — would have told a visitor it was talking to `ollama / qwen2.5:7b` and then
failed on connection refused.

Separately, `infra/` held a Docker Compose stack whose first service was Ollama,
plus a Dockerfile for a Prefect worker that ADR 0005 already explains is not
deployed because an always-on machine is not 0€.

## Decision

**1. The default is `gemini` / `gemini-2.5-flash-lite`** — what the pipeline has
actually been running. Ollama stays a fully supported, tested provider: it is a
laptop option for anyone with the RAM, one env var away, and the reason the
provider interface exists. It is simply not the default any more.

**2. `infra/` is deleted.** It described a deployment nobody performs, could not
be verified (no Docker on the development machine), and led with a service the
project no longer uses. The real deployment story is two sentences and both are
true: the app runs on Streamlit Community Cloud with its secrets set in that
dashboard, and the scheduler is a GitHub Actions cron. The worker-based path is
still documented where it belongs, in
[`orchestration/prefect.yaml`](../../orchestration/prefect.yaml).

**3. `.devcontainer/` is deleted.** It was the generated Streamlit template:
`pip3 install --user streamlit` against a `requirements.txt` this uv workspace
does not have. It would not have produced a working checkout.

## Consequences

A fresh clone with only a `motherduck_token` and a `GEMINI_API_KEY` now works
with no further configuration, and the app's live-configuration captions state
something true. The 0€ property is unchanged — Gemini's free tier costs nothing;
it is rate-limited, which the whole enrichment design already accounts for.

What this gives up is ADR 0005's stronger claim: the default now depends on a
third party's free tier, and if Google changes those terms the default breaks
where a local model would not. That risk is the reason the provider interface is
not being simplified away — switching back is `JMI_LLM_PROVIDER=ollama`.

Deleting `infra/` removes the project's only containerisation artifact. That is
a visible gap on a data-engineering portfolio, and it is the honest one: an
unbuilt, unrunnable Dockerfile demonstrates less than not claiming it.

## Alternatives considered

**Keep Ollama as the default and document the override.** It was already
documented, in `.env.example` and in ADR 0005, and the override was still
forgotten in two of the three places it was needed. A default that every caller
must remember to change is not a default.

**Fix `infra/` rather than delete it** — drop the Ollama service, keep a single
app container. Rejected: with no Docker available here it could not be built or
tested, so it would have gone back in as another untested claim. If a container
is ever needed, writing one then is cheaper than maintaining one that isn't.
