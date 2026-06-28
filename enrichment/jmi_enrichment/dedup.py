"""Cross-source deduplication recipes.

Per the dedup ADR, clustering runs in dbt's ``int_`` layer. This module is the
*shared deterministic recipe* so Python and dbt agree on the canonical key, plus
small helpers for the embedding-based edge-case pass (Phase 2).

The deterministic key intentionally drops source/source_job_id (those are
within-source identity) and normalizes title aggressively so the same role
posted on LinkedIn and Honeypot collapses to one cluster candidate.
"""

from __future__ import annotations

import hashlib
import math
import re
from collections.abc import Sequence

_WS = re.compile(r"\s+")
_NON_ALNUM = re.compile(r"[^a-z0-9 ]+")
# Gendered / boilerplate suffixes common in EU postings.
_NOISE = re.compile(
    r"\b(m/?w/?d|m/?f/?d|h/?m/?x|f/?m|all genders|remote|hybrid|fulltime|full[- ]time|"
    r"part[- ]time|contract|freelance)\b"
)


def normalize_title(title: str | None) -> str:
    if not title:
        return ""
    text = title.lower()
    text = re.sub(r"\([^)]*\)", " ", text)  # drop parentheticals
    text = _NOISE.sub(" ", text)
    text = _NON_ALNUM.sub(" ", text)
    return _WS.sub(" ", text).strip()


def _norm(value: str | None) -> str:
    if not value:
        return ""
    return _WS.sub(" ", _NON_ALNUM.sub(" ", value.lower())).strip()


def canonical_key(
    *, company_name: str | None, title: str | None, country_code: str | None
) -> str:
    """Deterministic cross-source cluster key (sha256 hex).

    Same recipe must be used in dbt (``int_job_postings_deduplicated``) so the
    two layers agree.
    """
    parts = [_norm(company_name), normalize_title(title), (country_code or "").lower()]
    return hashlib.sha256("\x1f".join(parts).encode("utf-8")).hexdigest()


def cosine_similarity(a: Sequence[float], b: Sequence[float]) -> float:
    """Cosine similarity for embedding edge-case comparison (Phase 2)."""
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)
