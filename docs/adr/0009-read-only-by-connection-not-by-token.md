# ADR 0009 — The app is read-only by connection, not by token

**Status:** Accepted
**Date:** 2026-09-16

## Context

The app is public. It serves a natural-language text-to-SQL agent, which by
design takes a stranger's sentence, has an LLM turn it into SQL, and runs that
SQL against the warehouse. Four guardrails were documented for it: SELECT/WITH
only, marts schema only, a forced LIMIT, and a **read-only connection**. The
first three are checks in this repo's own code, so they fail the way code fails:
a regex that misses a case, a keyword nobody thought of. The fourth is the one
that holds when the other three are wrong, which is the only reason to have it.

Two facts about how it was actually wired made that fourth guardrail a claim
rather than a fact.

**MotherDuck's free plan issues read/write tokens only.** Read scaling tokens
are a paid feature. So the credential in the deployed app's Secrets panel can
write to production, and no amount of careful token management on this plan
changes that. Advice to "use a read-only token for a public app" — which this
repo's own README gave — was advice the author could not follow.

**The connection retried without read-only on any failure.** The app's
`_live_connection` looped `for read_only in (True, False)`, with the comment
"some MotherDuck setups dislike read_only". Any exception on the first
attempt — a transient network error, a timeout, a cold start — silently produced
a **writable** connection to production, on which the agent then ran generated
SQL, while every page and the How It Works guardrail list went on saying the
connection was read-only.

Measured on 2026-09-16 against the live warehouse with the real read/write
token:

```
read_only=True : connected, 12,843 rows
                 CREATE refused -> "Cannot execute statement of type CREATE on
                 database ... which is attached in read-only mode"
```

The premise was simply false. MotherDuck does not dislike read-only
connections; it honours them, and it **enforces them server-side** — the refusal
above comes from the server, not from a check in this codebase. The fallback was
protecting against a problem that does not exist, at the cost of the guarantee
it was undermining.

## Decision

**1. The app opens exactly one kind of connection: read-only. There is no
fallback.** If a read-only connection cannot be opened, `_live_connection`
returns `None` and the app lands in demo mode, which announces itself on every
page. A labelled frozen sample is a better failure than unannounced write access
to production.

**2. Safety rests on the connection mode, not on the token's scope.** This is
the stronger property anyway, and it is the one available on a free plan: the
server refuses the write regardless of what the credential is allowed to do. A
read-only token, if the plan ever offers one, becomes defence in depth rather
than the load-bearing control.

**3. Two tests pin it.** One asserts the app asks for `read_only=True` and only
that; the other asserts an unreachable warehouse produces no second, writable
attempt. A comment saying "read-only" is what was there before, and it was
wrong.

## Consequences

The guardrail list on How It Works is now true as written. The failure mode
moves from "silently writable" to "visibly degraded", which is the direction
this project takes everywhere else: an unread posting says it is unread, a
frozen sample says it is frozen, and now an unreachable warehouse says that too
rather than reaching for more privilege.

What this costs: if MotherDuck ever does refuse a read-only attachment for some
configuration, the app will serve the demo sample instead of live data until
someone notices. That is a visible, diagnosable outage rather than an invisible
escalation, and the demo banner makes it obvious on the first page load.

This does not make the text-to-SQL agent safe against a determined attacker —
nothing here is hardened to that standard, and the README says so. It makes the
blast radius of a guard bypass a read of data that is already public on the
page, instead of a write to the warehouse.

## Alternatives considered

**Keep the fallback but log loudly when it triggers.** Rejected: nobody reads a
deployed Streamlit app's logs, and the page would still be claiming a read-only
connection while running on a writable one. A guarantee with a logged exception
is not a guarantee.

**Use a separate MotherDuck database with a copy of the marts for the app.**
Real isolation, and it would survive a writable connection. Rejected for now:
it doubles the storage on a free tier and adds a sync step to the daily
pipeline, to defend against a risk the connection mode already closes. Worth
revisiting if the app ever gains a write feature of its own, such as the
deferred offer tracker.

**Drop the text-to-SQL agent.** It is the component that creates this risk at
all. Rejected: it is also one of the most interesting things in the project, and
the risk is manageable — the agent is guard-railed, the connection cannot write,
and the data it can read is already rendered on the pages beside it.
