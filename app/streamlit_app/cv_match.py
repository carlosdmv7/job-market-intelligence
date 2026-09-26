"""CV matching logic — pure functions, no Streamlit, unit-testable.

Two tiers, by cost:

1. Deterministic (free, instant): intersect the CV text with the technology
   vocabulary the LLM already extracted from postings, then score every
   enriched posting by skill overlap. No LLM call, works on the whole corpus.
2. LLM deep-dive (one call, on demand): a single selected posting + the CV go
   to the configured provider for a match assessment with concrete suggestions.

The CV text itself never leaves the Streamlit session — it is not written to
the warehouse or anywhere else.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

import pandas as pd

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence

# The visa rubric doesn't matter here; the deep-dive is a career-coach read.
CV_MATCH_SYSTEM_PROMPT = """\
You are a blunt, practical technical recruiter reviewing a candidate's CV
against one specific job posting. The candidate is an EU citizen (no visa
needed) applying from Spain.

Answer in concise markdown with exactly these sections:
1. **Match** — a percentage (your honest estimate) and one sentence why.
2. **Strengths** — up to 3 bullets: where the CV genuinely fits this posting.
3. **Gaps** — up to 3 bullets: what the posting asks for that the CV lacks.
   If a gap is fatal (hard requirement clearly not met), say so plainly.
4. **CV suggestions** — up to 3 bullets: concrete, specific edits to this CV
   for this posting (rephrase X, surface project Y, quantify Z). No generic
   advice like "tailor your CV".

Base everything only on the two texts provided. Never invent experience the
CV doesn't contain."""


#: Terms the enrichment extracts that name a field or a job, not a skill. Every
#: data CV contains them, so they would match every CV and inflate every score
#: equally — and they are dropped from the postings' stacks too, not only from
#: the CV's: a term the CV can never match must not count as a gap either.
GENERIC_TERMS = frozenset(
    {
        # the originals
        "data", "ai", "it", "software", "cloud", "microsoft", "ms office", "office", "tech",
        # fields and job titles, drawn from the production vocabulary (Sep 2026)
        "analytics", "advanced analytics", "data & analytics", "data analysis",
        "data analytics", "data science", "data engineering", "data platform",
        "data pipelines", "bi", "business intelligence", "reporting", "big data",
        "artificial intelligence", "software engineering", "databases",
        "data-intensive solutions", "visual data", "pipelines", "dashboards", "saas",
    }
)  # fmt: skip

#: A posting is scored as if it asked for this many more technologies than it
#: names. Adzuna returns a snippet, so a quarter of the scorable postings name a
#: single technology, and any CV with it scored 100% — above a posting whose
#: six named technologies it covers five of. With one unnamed requirement
#: assumed, 1 of 1 is 50%, 2 of 2 is 67% and 5 of 6 is 71%: a score is trusted
#: only as far as the evidence behind it goes. The same idea as the empirical-
#: Bayes benchmark in the sibling spanish-housing-radar project.
UNNAMED_REQUIREMENTS = 1


def is_generic(term: str) -> bool:
    return term.lower() in GENERIC_TERMS


def useful_vocabulary(vocabulary: Iterable[str]) -> list[str]:
    """Drop hypergeneric terms and case duplicates; keep order.

    Callers pass the vocabulary frequency-sorted, so the spelling kept is the
    commonest: the LLM writes "machine learning" 127 times and "Machine
    Learning" once, and the CV used to show both as separate skills.
    """
    seen: set[str] = set()
    kept = []
    for term in vocabulary:
        if is_generic(term) or term.lower() in seen:
            continue
        seen.add(term.lower())
        kept.append(term)
    return kept


def extract_skills(cv_text: str, vocabulary: Iterable[str]) -> list[str]:
    """Return the vocabulary terms present in the CV text.

    Word-boundary matching that tolerates non-alphanumeric tech names
    (c++, c#, .net): a term matches when not glued to adjacent letters/digits.
    """
    text = cv_text.lower()
    found = []
    for term in vocabulary:
        pattern = rf"(?<![a-z0-9]){re.escape(term.lower())}(?![a-z0-9])"
        if re.search(pattern, text):
            found.append(term)
    return found


def score_jobs(jobs: pd.DataFrame, cv_skills: Sequence[str]) -> pd.DataFrame:
    """Score each posting by skill overlap, discounted for thin evidence.

    ``match_pct`` is ``|cv ∩ job| / (|job| + UNNAMED_REQUIREMENTS)`` over the
    posting's non-generic technologies. Expects a ``technologies`` column of
    lists; rows left with none (unenriched, or naming only generic terms) are
    dropped, since there is nothing to score. Adds ``matched``, ``missing``,
    ``n_techs`` and ``match_pct``, sorted best-first.
    """

    def _as_list(value) -> list:
        # DuckDB array columns come back as pd.NA (not None) when NULL.
        if value is None or (pd.api.types.is_scalar(value) and pd.isna(value)):
            return []
        return [t for t in value if not is_generic(t)]

    have = {s.lower() for s in cv_skills}
    scored = jobs.copy()
    scored["technologies"] = scored["technologies"].map(_as_list)
    scored = scored[scored["technologies"].map(len) > 0]
    scored["matched"] = scored["technologies"].map(
        lambda ts: sorted(t for t in ts if t.lower() in have)
    )
    scored["missing"] = scored["technologies"].map(
        lambda ts: sorted(t for t in ts if t.lower() not in have)
    )
    scored["n_techs"] = scored["technologies"].map(len)
    scored["match_pct"] = scored["matched"].map(len) / (scored["n_techs"] + UNNAMED_REQUIREMENTS)
    # Equal scores: the posting that names more of its stack first.
    return scored.sort_values(["match_pct", "n_techs", "last_seen_at"], ascending=False)


def build_deep_dive_prompt(
    cv_text: str,
    *,
    title: str,
    company: str | None,
    description: str | None,
    technologies: Sequence[str],
    max_chars: int = 6000,
) -> str:
    """User-turn payload for the one-call LLM deep-dive."""

    def clip(text: str) -> str:
        return text[:max_chars] + " …[truncated]" if len(text) > max_chars else text

    return "\n".join(
        [
            f"JOB POSTING — {title} at {company or 'unknown company'}",
            f"Technologies extracted from it: {', '.join(technologies) or '(none)'}",
            "",
            clip(description or "(no description captured)"),
            "",
            "CANDIDATE CV:",
            clip(cv_text),
        ]
    )
