"""Deterministic salary parser: raw text -> jmi_core.Salary.

Not LLM work — this is a Phase-2 deterministic transform over
``JobPosting.salary_raw``. It lives here as a reusable contract; downstream it
runs in dbt staging (or is called from a Python model). Handles EU and US
number formats, k-suffixes, ranges, periods, gross/net, and ES/NL/DE/PT cues.
"""

from __future__ import annotations

import re

from jmi_core.schema import SalaryPeriod
from jmi_core.schema.values import Salary

_CURRENCY = [
    ("EUR", ("€", "eur", "euro")),
    ("GBP", ("£", "gbp", "quid")),
    ("USD", ("$", "usd")),
    ("CHF", ("chf",)),
]

_PERIOD = [
    (SalaryPeriod.YEAR, ("year", "yr", "annum", "annual", "p.a", "pa ", "/yr", "año", "anual", "jaar", "jahr", "ano", "anual")),
    (SalaryPeriod.MONTH, ("month", "/mo", "p.m", "mensual", "mes", "maand", "monat", "mês", "mensal")),
    (SalaryPeriod.DAY, ("day", "/day", "daily", "día", "dia", "dag", "tag")),
    (SalaryPeriod.HOUR, ("hour", "/hr", "hourly", "hora", "uur", "stunde")),
]

_GROSS = ("gross", "bruto", "brutos", "bruto/", "brutto", "brut")
_NET = ("net", "neto", "netto", "líquido", "liquido")
_ESTIMATED = ("estimated", "approx", "aprox", "circa", "around", "up to", "hasta")

# A number with optional thousands/decimal separators and optional k/m suffix.
_NUMBER = re.compile(r"\d[\d.,]*\s*[kKmM]?")


def _to_number(token: str) -> float | None:
    token = token.strip()
    mult = 1.0
    if token[-1:] in "kK":
        mult, token = 1_000.0, token[:-1].strip()
    elif token[-1:] in "mM":
        mult, token = 1_000_000.0, token[:-1].strip()

    has_dot, has_comma = "." in token, "," in token
    if has_dot and has_comma:
        # The last separator is the decimal one (covers 1.234,56 and 1,234.56).
        if token.rfind(",") > token.rfind("."):
            token = token.replace(".", "").replace(",", ".")
        else:
            token = token.replace(",", "")
    elif has_comma:
        # "60,000" -> thousands; "60,5" -> decimal.
        token = token.replace(",", "") if re.search(r",\d{3}\b", token) else token.replace(",", ".")
    elif has_dot:
        # "60.000" -> thousands; "60.5" -> decimal.
        token = token.replace(".", "") if re.search(r"\.\d{3}\b", token) else token

    try:
        return float(token) * mult
    except ValueError:
        return None


def _first(text: str, table: list[tuple[object, tuple[str, ...]]]) -> object | None:
    for value, needles in table:
        if any(n in text for n in needles):
            return value
    return None


def parse_salary(raw: str | None) -> Salary | None:
    """Parse a raw salary string. Returns None if nothing usable is found."""
    if not raw or not raw.strip():
        return None
    text = raw.lower()

    currency = _first(text, _CURRENCY)
    period = _first(text, _PERIOD)

    is_gross: bool | None = None
    if any(g in text for g in _GROSS):
        is_gross = True
    elif any(n in text for n in _NET):
        is_gross = False

    is_estimated = True if any(e in text for e in _ESTIMATED) else None

    numbers = [n for tok in _NUMBER.findall(raw) if (n := _to_number(tok)) is not None]
    # Drop spurious tiny tokens (e.g. a stray "2" from "2 days") when larger
    # comp figures are present.
    if numbers:
        big = [n for n in numbers if n >= 100]
        numbers = big or numbers

    min_amount = max_amount = None
    if len(numbers) >= 2:
        min_amount, max_amount = min(numbers[:2]), max(numbers[:2])
    elif len(numbers) == 1:
        min_amount = max_amount = numbers[0]

    if min_amount is None and currency is None:
        return None

    return Salary(
        min_amount=min_amount,
        max_amount=max_amount,
        currency=currency,  # type: ignore[arg-type]
        period=period,  # type: ignore[arg-type]
        is_gross=is_gross,
        is_estimated=is_estimated,
    )
