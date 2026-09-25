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


def repair_mojibake(value: str | None) -> str | None:
    """Undo UTF-8 text that was decoded as Latin-1 somewhere upstream.

    RemoteOK's API serves some postings double-encoded — "MecÃ¡nico" for
    "Mecánico", Arabic as "Ø§Ù..." — in about one posting in ten (checked
    2026-09-25: 160 of 1,678 in the warehouse; 5 of 99 in one live response).
    The bytes are all there, so re-encoding as Latin-1 and decoding as UTF-8
    restores the original.

    Only applied when that round trip succeeds strictly. Real Latin-1 text
    ("Café", "Zürich") is not valid UTF-8 once re-encoded, so it fails the
    decode and comes back untouched; text with characters beyond Latin-1 cannot
    be re-encoded at all, so it is left alone too.
    """
    if not value or value.isascii():
        return value
    try:
        repaired = value.encode("latin-1").decode("utf-8")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return value
    return repaired


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
