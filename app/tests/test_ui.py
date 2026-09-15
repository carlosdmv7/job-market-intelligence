"""The display helpers that turn warehouse rows into what a reader sees."""

from __future__ import annotations

import pandas as pd
from streamlit_app.ui import add_salary_eur, flag, market_label


def test_flag_is_derived_from_any_valid_iso_code():
    assert flag("NL") == "🇳🇱"
    assert flag("se") == "🇸🇪"
    # Derived, not tabulated: a country the boards surface tomorrow still works.
    assert flag("PT") == "🇵🇹"
    assert flag("XYZ") == ""
    assert flag("1A") == ""


def test_market_label_names_the_known_markets_and_flags_the_rest():
    assert market_label("NL") == "🇳🇱 Netherlands"
    assert market_label("PT") == "🇵🇹 PT"
    assert market_label(None) == "🌍 Remote / global"
    assert market_label(pd.NA) == "🌍 Remote / global"


def test_bare_numbers_are_euros_when_the_posting_is_from_the_euro_area():
    """Adzuna quotes per-country salaries with no currency symbol at all.

    The currency is carried by the endpoint, not the text, so refusing every
    unlabelled figure emptied the salary column on all 818 open roles while 98
    of them had a band sitting in salary_raw.
    """
    df = pd.DataFrame(
        {
            "salary_raw": [
                "58800-79200",  # Adzuna NL -> euros
                "58800-79200",  # same text from Sweden -> kronor, not ours
                "USD 40000-180000",  # named other currency -> no invented FX
                "960-1680",  # not an annual band, whatever it is
                "50.000 - 60.000 EUR per year",  # says so itself
                None,
            ],
            "country_code": ["NL", "SE", None, "NL", "DE", "ES"],
        }
    )
    got = add_salary_eur(df)["salary_eur"].tolist()
    assert got[0] == 79200
    assert pd.isna(got[1])
    assert pd.isna(got[2])
    assert pd.isna(got[3])
    assert got[4] == 60000
    assert pd.isna(got[5])


def test_salary_column_is_numeric_even_when_nothing_parses():
    """An object column of Nones renders as the literal string "None"."""
    df = pd.DataFrame({"salary_raw": [None, None], "country_code": ["NL", "NL"]})
    assert add_salary_eur(df)["salary_eur"].dtype.kind == "f"
