from __future__ import annotations

import pytest

from jmi_core.schema import SalaryPeriod
from jmi_enrichment.salary import parse_salary


@pytest.mark.parametrize(
    ("raw", "lo", "hi", "currency", "period"),
    [
        ("€60.000 - €75.000 per year", 60000, 75000, "EUR", SalaryPeriod.YEAR),
        ("EUR 70000-90000 year", 70000, 90000, "EUR", SalaryPeriod.YEAR),
        ("$120,000/yr", 120000, 120000, "USD", SalaryPeriod.YEAR),
        ("60k - 75k EUR", 60000, 75000, "EUR", None),
        ("£45,000 per annum", 45000, 45000, "GBP", SalaryPeriod.YEAR),
        ("45.000€ brutos/año", 45000, 45000, "EUR", SalaryPeriod.YEAR),
        ("€5.500 per maand", 5500, 5500, "EUR", SalaryPeriod.MONTH),
    ],
)
def test_parse_ranges_currencies_periods(raw, lo, hi, currency, period):
    s = parse_salary(raw)
    assert s is not None
    assert s.min_amount == lo
    assert s.max_amount == hi
    assert s.currency == currency
    assert s.period == period


def test_gross_net_and_estimated():
    s = parse_salary("45.000€ brutos/año")
    assert s.is_gross is True
    net = parse_salary("3.000€ netto per maand")
    assert net.is_gross is False
    est = parse_salary("up to €90,000")
    assert est.is_estimated is True


def test_european_decimal_comma():
    s = parse_salary("1.234,56 EUR")
    assert s.min_amount == pytest.approx(1234.56)


def test_returns_none_when_no_signal():
    assert parse_salary(None) is None
    assert parse_salary("competitive salary") is None  # no number, no currency
