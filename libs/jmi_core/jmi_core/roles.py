"""Which job titles this project is about.

The definition lives in core because three layers need the same answer and a
disagreement between them is silent: the scrapers use it to decide what to
ingest, the enrichment selector uses it to decide where scarce LLM quota goes,
and dbt mirrors it as ``jmi_is_target_role`` to flag rows already in the
warehouse. ``scrapers/tests/test_target_role_parity.py`` pins the Python and
SQL spellings against each other over real corpus titles.
"""

from __future__ import annotations

import re

#: The same scope decision as DATA_ROLE_QUERIES, for the boards that have no
#: server-side search. Adzuna and JobTech are asked for data roles; Remotive,
#: Arbeitnow and RemoteOK hand back their whole board, so the filter has to
#: happen here instead.
#:
#: Without it those three were 10,384 of the corpus's 12,584 postings, and
#: roughly nine in ten were Steuerberater, hotel managers and sales executives
#: — noise that drowned the data roles in every list the app renders.
#:
#: Matched against the *title* only. A description mentioning "data" in passing
#: says nothing about the role; a title is the board's own summary of it.
_TARGET_ROLE_TERMS: tuple[str, ...] = (
    r"data",  # data engineer/analyst/scientist/platform/governance/ops
    r"analytics?",
    r"machine\s+learning",
    r"ml\s*ops",
    r"ml\s+engineer",
    r"\bml\b",
    r"ai\s+engineer",
    r"\bai\b\s*/\s*ml",
    r"business\s+intelligence",
    r"\bbi\b",
    r"\betl\b",
    r"\bdbt\b",
    r"data\s*warehouse",
    r"datawarehouse",
    r"big\s*data",
    r"\bllm\b",
)

#: Every term is word-anchored on both sides. An early version anchored only the
#: front and matched "BI" inside "Bildung" — which is the kind of bug that
#: quietly re-admits the noise the filter exists to remove.
TARGET_ROLE_PATTERN = re.compile(
    "(?:" + "|".join(t if t.startswith(r"\b") else rf"\b{t}\b" for t in _TARGET_ROLE_TERMS) + ")",
    re.IGNORECASE,
)


#: "Bi-lingual" is a word "BI" matches on its own, and multilingual sales roles
#: are a staple of Dublin's EMEA hubs ("Account Executive (Bi-lingual)"). It is
#: removed before matching rather than excluded by the pattern: a lookahead
#: would do it here, but DuckDB's RE2 has none, and the SQL mirror must match.
#: Removing the word, rather than dropping every title that has it, keeps
#: "Bi-lingual Data Analyst", which is a data role.
BILINGUAL_PATTERN = re.compile(r"\bbi[\s-]+lingual\b", re.IGNORECASE)


def is_target_role(title: str | None) -> bool:
    """Is this title a data/analytics/ML role worth ingesting?"""
    return bool(title and TARGET_ROLE_PATTERN.search(BILINGUAL_PATTERN.sub(" ", title)))
