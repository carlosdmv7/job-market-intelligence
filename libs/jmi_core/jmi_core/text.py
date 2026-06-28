"""Small text utilities used at ingestion time.

Language detection here is the cheap, deterministic kind (which language is the
posting written in) — it populates ``JobPosting.detected_language``. The LLM
enrichment never translates; it reads the original text (ES/NL/DE/PT/EN).
"""

from __future__ import annotations

import re

_TAG = re.compile(r"<[^>]+>")
_WS = re.compile(r"\s+")


def strip_html(value: str | None) -> str | None:
    """Best-effort HTML-to-text for descriptions that arrive as markup."""
    if not value:
        return value
    text = _TAG.sub(" ", value)
    text = (
        text.replace("&nbsp;", " ")
        .replace("&amp;", "&")
        .replace("&lt;", "<")
        .replace("&gt;", ">")
        .replace("&#39;", "'")
        .replace("&quot;", '"')
    )
    return _WS.sub(" ", text).strip()


def detect_language(text: str | None, *, min_chars: int = 20) -> str | None:
    """Return an ISO 639-1 code, or None if undetectable / text too short.

    Uses ``langdetect`` when available; returns None rather than raising so a
    detection failure never blocks ingestion.
    """
    if not text or len(text.strip()) < min_chars:
        return None
    try:
        from langdetect import DetectorFactory, detect

        DetectorFactory.seed = 0  # deterministic
        code = detect(text)
        return code.split("-")[0].lower() if code else None
    except Exception:
        return None
