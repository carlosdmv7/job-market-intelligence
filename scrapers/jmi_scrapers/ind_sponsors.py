"""IND recognised-sponsor register (Netherlands).

A free, public, authoritative list (~12.8k organisations) of employers legally
allowed to sponsor work/residence permits in the Netherlands, published by the
IND and updated monthly. We scrape the single server-rendered HTML table
(organisation name + KvK number) and emit it as a dbt seed CSV.

Cross-referencing a job posting's company against this register yields a
*deterministic, auditable* visa-sponsor signal — no LLM, no rate limits, no cost.
This is the strongest visa signal in the project and it does not depend on the
(rate-limited) LLM enrichment.

Source: https://ind.nl/en/public-register-recognised-sponsors
"""

from __future__ import annotations

import argparse
import csv
import re
import unicodedata
from html import unescape
from pathlib import Path

from jmi_core.logging import get_logger
from jmi_scrapers.base import HttpSession

log = get_logger(__name__)

IND_REGISTER_URL = (
    "https://ind.nl/en/public-register-recognised-sponsors/"
    "public-register-regular-labour-and-highly-skilled-migrants"
)

# Repo-root/dbt/jmi/seeds/recognised_sponsors.csv (dbt seed location).
_SEED_PATH = (
    Path(__file__).resolve().parents[2] / "dbt" / "jmi" / "seeds" / "recognised_sponsors.csv"
)

# Legal-form / noise tokens stripped before matching company names, so that
# "ASML Netherlands B.V." and "ASML" collapse to the same key.
_NOISE_TOKENS = frozenset(
    {
        "bv",
        "nv",
        "vof",
        "cv",
        "ua",
        "ba",
        "holding",
        "holdings",
        "group",
        "groep",
        "international",
        "nederland",
        "netherlands",
        "the",
        "and",
        "inc",
        "ltd",
        "llc",
        "gmbh",
        "sa",
        "company",
        "co",
        "corp",
        "corporation",
        "europe",
        "global",
    }
)
# Legal forms written with dots/spaces (b.v., n.v., v.o.f., ...) — removed before
# punctuation stripping so they don't survive as stray single-letter tokens.
_LEGAL_RE = re.compile(
    r"\b(?:[bn]\W*v|v\W*o\W*f|c\W*v|u\W*a|b\W*a|s\W*a|s\W*r\W*l)\b", re.IGNORECASE
)
_TAG_RE = re.compile(r"<[^>]+>")
_TBODY_RE = re.compile(r"<tbody.*?</tbody>", re.S)
_TR_RE = re.compile(r"<tr.*?</tr>", re.S)
_TH_RE = re.compile(r"<th[^>]*>(.*?)</th>", re.S)
_TD_RE = re.compile(r"<td[^>]*>(.*?)</td>", re.S)


def _text(fragment: str) -> str:
    return unescape(_TAG_RE.sub("", fragment)).strip()


def normalize_company(name: str | None) -> str:
    """Normalize a company name for cross-source matching.

    Lowercases, strips accents and punctuation, drops legal forms / noise tokens
    and collapses whitespace. Deterministic and dependency-free.
    """
    if not name:
        return ""
    s = unicodedata.normalize("NFKD", name)
    s = "".join(c for c in s if not unicodedata.combining(c)).lower()
    s = _LEGAL_RE.sub(" ", s)
    s = re.sub(r"[^a-z0-9 ]+", " ", s)
    tokens = [t for t in s.split() if t and t not in _NOISE_TOKENS]
    return " ".join(tokens)


def parse_register(html: str) -> list[tuple[str, str]]:
    """Return ``[(organisation, kvk_number)]`` parsed from the register HTML."""
    body_m = _TBODY_RE.search(html)
    body = body_m.group(0) if body_m else html
    rows: list[tuple[str, str]] = []
    for tr in _TR_RE.findall(body):
        th = _TH_RE.search(tr)
        if not th:
            continue
        name = _text(th.group(1))
        if not name or name.lower() == "organisation":  # skip header-ish rows
            continue
        td = _TD_RE.search(tr)
        kvk = _text(td.group(1)) if td else ""
        rows.append((name, kvk))
    return rows


def fetch_sponsors(http: HttpSession | None = None) -> list[tuple[str, str]]:
    """Download and parse the full recognised-sponsor register."""
    own = http is None
    http = http or HttpSession(headers={"Accept": "text/html"})
    try:
        html = http.get_text(IND_REGISTER_URL)
    finally:
        if own:
            http.close()
    rows = parse_register(html)
    log.info("ind.fetch", sponsors=len(rows))
    return rows


def write_seed(rows: list[tuple[str, str]], path: Path = _SEED_PATH) -> Path:
    """Write the register to a dbt seed CSV (raw source data).

    Name normalization for matching is a dbt concern (the ``jmi_normalize_company``
    macro), applied identically to both this list and job-posting company names,
    so it lives in the warehouse layer rather than being precomputed here.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(["organisation", "kvk_number"])
        writer.writerows(rows)
    return path


def main() -> None:
    parser = argparse.ArgumentParser(description="Refresh the IND recognised-sponsor dbt seed")
    parser.add_argument("--out", type=Path, default=_SEED_PATH)
    args = parser.parse_args()
    rows = fetch_sponsors()
    path = write_seed(rows, args.out)
    print(f"wrote {len(rows)} recognised sponsors -> {path}")


if __name__ == "__main__":
    main()
