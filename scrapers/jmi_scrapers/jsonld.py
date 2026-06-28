"""schema.org/JobPosting (JSON-LD) extraction.

Most structured job boards (StepStone, IrishJobs, ITJobs, many ATS pages)
embed a ``<script type="application/ld+json">`` JobPosting on the detail page.
This module pulls those blocks out of raw HTML and maps them to the field names
:meth:`BaseScraper.build_posting` expects — so a new source is often just
"fetch the detail URL, call :func:`jobposting_to_fields`".

Pure, dependency-free, offline-testable.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from typing import Any

_SCRIPT_RE = re.compile(
    r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
    re.IGNORECASE | re.DOTALL,
)


def iter_jsonld_blocks(html: str) -> list[Any]:
    """Return every parsed JSON-LD object found in the HTML (lenient)."""
    blocks: list[Any] = []
    for match in _SCRIPT_RE.finditer(html):
        raw = match.group(1).strip()
        if not raw:
            continue
        try:
            blocks.append(json.loads(raw))
        except json.JSONDecodeError:
            continue
    return blocks


def _is_jobposting(node: Any) -> bool:
    if not isinstance(node, dict):
        return False
    node_type = node.get("@type")
    if isinstance(node_type, list):
        return any(str(t).lower() == "jobposting" for t in node_type)
    return str(node_type).lower() == "jobposting"


def extract_jobposting_nodes(html: str) -> list[dict[str, Any]]:
    """Find all JobPosting nodes, descending into lists and ``@graph``."""
    found: list[dict[str, Any]] = []
    stack = list(iter_jsonld_blocks(html))
    while stack:
        node = stack.pop()
        if isinstance(node, list):
            stack.extend(node)
        elif isinstance(node, dict):
            if _is_jobposting(node):
                found.append(node)
            if isinstance(node.get("@graph"), list):
                stack.extend(node["@graph"])
    return found


def _parse_dt(value: Any) -> datetime | None:
    """Parse a schema.org date/datetime into a UTC, tz-aware datetime."""
    if not value or not isinstance(value, str):
        return None
    text = value.strip().replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        try:
            dt = datetime.strptime(text[:10], "%Y-%m-%d")
        except ValueError:
            return None
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt.astimezone(timezone.utc)


def _org_name(node: dict[str, Any]) -> str | None:
    org = node.get("hiringOrganization")
    if isinstance(org, dict):
        name = org.get("name")
        return str(name) if name else None
    return str(org) if org else None


def _location(node: dict[str, Any]) -> tuple[str | None, str | None]:
    """Return (location_raw, ISO-3166 alpha-2 country_code or None)."""
    loc = node.get("jobLocation")
    if isinstance(loc, list):
        loc = loc[0] if loc else None
    if not isinstance(loc, dict):
        return None, None
    addr = loc.get("address")
    if not isinstance(addr, dict):
        return (str(addr) if addr else None), None
    parts = [
        addr.get("addressLocality"),
        addr.get("addressRegion"),
        addr.get("addressCountry"),
    ]
    country = addr.get("addressCountry")
    if isinstance(country, dict):
        country = country.get("name") or country.get("addressCountry")
    code = country if isinstance(country, str) and len(country) == 2 else None
    location_raw = ", ".join(str(p) for p in parts if p) or None
    return location_raw, (code.upper() if code else None)


def _salary(node: dict[str, Any]) -> str | None:
    base = node.get("baseSalary")
    if not isinstance(base, dict):
        return str(base) if base else None
    currency = base.get("currency") or ""
    value = base.get("value")
    if isinstance(value, dict):
        lo, hi = value.get("minValue"), value.get("maxValue")
        unit = value.get("unitText") or value.get("unit") or ""
        single = value.get("value")
        if lo is not None and hi is not None:
            amount = f"{lo}-{hi}"
        elif single is not None:
            amount = str(single)
        else:
            return None
        return " ".join(p for p in (currency, amount, str(unit).lower()) if p).strip() or None
    return f"{currency} {value}".strip() or None


def _employment_type(node: dict[str, Any]) -> str | None:
    et = node.get("employmentType")
    if isinstance(et, list):
        return ", ".join(str(x) for x in et) or None
    return str(et) if et else None


def jobposting_to_fields(node: dict[str, Any]) -> dict[str, Any]:
    """Map a JSON-LD JobPosting node to ``build_posting`` keyword args.

    Returns only fields present in the node; ``title`` is required downstream.
    """
    location_raw, country_code = _location(node)
    identifier = node.get("identifier")
    if isinstance(identifier, dict):
        identifier = identifier.get("value")
    return {
        "title": node.get("title"),
        "company_name": _org_name(node),
        "description_raw": node.get("description"),
        "location_raw": location_raw,
        "country_code": country_code,
        "posted_at": _parse_dt(node.get("datePosted")),
        "valid_through": _parse_dt(node.get("validThrough")),
        "salary_raw": _salary(node),
        "employment_type_raw": _employment_type(node),
        "apply_url": node.get("url"),
        "source_job_id": str(identifier) if identifier else None,
        "raw_payload": node,
    }
