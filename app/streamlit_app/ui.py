"""App-specific visual layer on top of the portable brand chrome.

Everything colour- or typography-related comes from :mod:`streamlit_app.theme`
(the drop-in shared file); this module adds only what is specific to *this*
domain — market labels, the visa vocabulary, and the chart helpers built on
them. Only current APIs: ``alt.theme`` (Altair 6) and ``width="stretch"``
(Streamlit), no CSS injection.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

import altair as alt
import streamlit as st

from streamlit_app.theme import (
    PETROL_900,
    RUST_500,
    RUST_700,
    SURFACE,
    TEAL_700,
    show,
)

if TYPE_CHECKING:
    import pandas as pd

__all__ = [
    "MARKETS",
    "SPONSORSHIP_SQL",
    "VISA_LABELS",
    "flag",
    "hbar",
    "market_label",
    "show",
    "table",
    "visa_label",
]

# Re-exported so pages import their colours from one place.
PRIMARY = PETROL_900
ACCENT = RUST_500
GOOD = TEAL_700
SURFACE_COLOR = SURFACE

# --- the sponsorship roll-up ------------------------------------------------
# The whole point of the project is that a *missing* LLM read is not a negative
# one. These four buckets keep that distinction visible everywhere: "not yet
# classified" (we haven't looked) is a different colour and a different word
# from "no evidence" (we looked, the text says nothing).
RECOGNISED = "Recognised sponsor (IND)"
LLM_ONLY = "LLM-positive only"
UNCLASSIFIED = "Not yet classified"
NO_EVIDENCE = "No sponsorship evidence"

#: SQL that derives the bucket in the warehouse, so charts and tables agree
#: with the agent and with each other. Kept here next to the labels it emits.
SPONSORSHIP_SQL = f"""
case
    when is_recognised_sponsor                          then '{RECOGNISED}'
    when visa_status in ('explicit_yes', 'likely_yes')  then '{LLM_ONLY}'
    when not is_enriched                                then '{UNCLASSIFIED}'
    else '{NO_EVIDENCE}'
end
"""


# --- the LLM's own 5-value read ---------------------------------------------
# Ordered good -> bad. Rendered as text, never as a colour scale: the five
# values only ever appear on a posting card, one at a time.
VISA_LABELS = {
    "explicit_yes": "✅ Sponsorship offered (explicit)",
    "likely_yes": "🟢 Sponsorship likely",
    "unclear": "⚪ No signal in the text",
    "likely_no": "🟠 Sponsorship unlikely",
    "explicit_no": "🔴 No sponsorship (explicit)",
}
#: What to say when the row was never sent to the LLM. Deliberately *not* one
#: of the values above — an unenriched posting has no LLM read at all.
NOT_CLASSIFIED_LABEL = "◻️ Not yet classified"


def visa_label(status, *, is_enriched=True) -> str:
    import pandas as pd

    if is_enriched is not None and not pd.isna(is_enriched) and not is_enriched:
        return NOT_CLASSIFIED_LABEL
    if status is None or (pd.api.types.is_scalar(status) and pd.isna(status)):
        return NOT_CLASSIFIED_LABEL
    return VISA_LABELS.get(status, str(status))


#: Markets with a dedicated local corpus — the ones the scrapers query by name.
#: Spelled out because "Netherlands" reads faster than "NL" in a legend.
MARKETS = {
    "NL": "🇳🇱 Netherlands",
    "SE": "🇸🇪 Sweden",
    "DE": "🇩🇪 Germany",
    "ES": "🇪🇸 Spain",
}


def flag(country_code: str) -> str:
    """An ISO-3166 alpha-2 code as its flag emoji.

    Derived rather than tabulated: the two regional-indicator codepoints for a
    country's letters *are* its flag, so every valid code gets a flag without a
    lookup table that silently omits whichever country the boards surface next.
    """
    code = country_code.strip().upper()
    if len(code) != 2 or not code.isalpha():
        return ""
    return "".join(chr(0x1F1E6 + ord(c) - ord("A")) for c in code)


def market_label(country_code: str | None) -> str:
    """Display name for a market: flag plus a human name wherever possible."""
    # `x != x` catches float NaN but *raises* on pd.NA, which DuckDB returns
    # for some nullable dtypes — so go through pd.isna instead.
    import pandas as pd

    if country_code is None or (pd.api.types.is_scalar(country_code) and pd.isna(country_code)):
        return "🌍 Remote / global"
    code = str(country_code)
    if code in MARKETS:
        return MARKETS[code]
    emoji = flag(code)
    return f"{emoji} {code}" if emoji else code


def table(df: pd.DataFrame, **kwargs) -> None:
    st.dataframe(df, width="stretch", hide_index=True, **kwargs)


def selected_rows(event: Any) -> list[int]:
    """Positional indices selected in an ``on_select="rerun"`` dataframe.

    Streamlit's return type for that call is ``DataframeState``, which its own
    stubs declare without the ``selection`` attribute the runtime always sets —
    so every caller would otherwise carry the same type: ignore. One typed
    accessor instead, and the pages read better for it.
    """
    selection = getattr(event, "selection", None)
    return list(getattr(selection, "rows", []) or [])


def hbar(
    df: pd.DataFrame,
    label: str,
    value: str,
    *,
    title: str | None = None,
    color: str = PETROL_900,
    value_title: str | None = None,
    height: int | None = None,
) -> alt.Chart:
    """Horizontal magnitude bars: rounded data-ends, recessive x-grid, hover."""
    h = height or max(150, len(df) * 30 + 12)
    return (
        alt.Chart(df)
        .mark_bar(color=color)
        .encode(
            y=alt.Y(f"{label}:N", sort="-x", title=None, axis=alt.Axis(labelLimit=220)),
            x=alt.X(f"{value}:Q", title=value_title, axis=alt.Axis(grid=True, tickCount=4)),
            tooltip=[
                alt.Tooltip(f"{label}:N", title=label.replace("_", " ")),
                alt.Tooltip(f"{value}:Q", title=value_title or value.replace("_", " ")),
            ],
        )
        .properties(height=h, title=title or "")
    )


# --- parsed salary ----------------------------------------------------------
#: Periods -> multiplier to a yearly figure. Days/hours use the Dutch full-time
#: norm (260 working days, 8h) — stated here rather than buried in a lambda.
_ANNUALISE = {"year": 1, "month": 12, "day": 260, "hour": 260 * 8}

#: Euro-area countries. Adzuna quotes its per-country salaries as bare numbers
#: — "58800-79200", no symbol — so the currency is carried by the endpoint the
#: posting came from, not by the text. Without this the parser correctly
#: refused every one of them, and the salary column was empty on all 818 open
#: roles while 98 of them had a figure sitting in `salary_raw`.
_EURO_COUNTRIES = frozenset(
    {
        "AT",
        "BE",
        "CY",
        "DE",
        "EE",
        "ES",
        "FI",
        "FR",
        "GR",
        "HR",
        "IE",
        "IT",
        "LT",
        "LU",
        "LV",
        "MT",
        "NL",
        "PT",
        "SI",
        "SK",
    }
)

#: Below this, an "annual" figure is not one. Adzuna occasionally passes
#: through a monthly or hourly band without saying so ("960-1680"), and a
#: posting rendered as "EUR 1,680/yr" is a wrong number, which is worse here
#: than a blank one.
_MIN_CREDIBLE_ANNUAL_EUR = 12_000


def add_salary_eur(df: pd.DataFrame) -> pd.DataFrame:
    """Add ``salary_eur``: the raw salary text annualised, EUR only.

    Reuses the deterministic parser from ``jmi_enrichment`` (the same tested
    contract the pipeline documents) rather than re-implementing it in SQL.

    A figure counts as euros when the text says so, or when the text names no
    currency at all and the posting is from a euro-area country — that second
    case is inference, but the narrow kind: the number came from a per-country
    endpoint that quotes in the local currency by construction. A posting in a
    *named* other currency is left null, because converting it would mean
    inventing an FX rate and a rate date, and this app does not do that.
    """
    import pandas as pd

    from jmi_enrichment.salary import parse_salary

    def _one(raw, country) -> float | None:
        if raw is None or (pd.api.types.is_scalar(raw) and pd.isna(raw)):
            return None
        parsed = parse_salary(str(raw))
        if parsed is None:
            return None
        if parsed.currency is None:
            code = None if country is None or pd.isna(country) else str(country).upper()
            if code not in _EURO_COUNTRIES:
                return None
        elif parsed.currency != "EUR":
            return None
        amount = parsed.max_amount or parsed.min_amount
        if amount is None:
            return None
        factor = _ANNUALISE.get(str(parsed.period) if parsed.period else "year")
        if not factor:
            return None
        annual = round(amount * factor)
        return annual if annual >= _MIN_CREDIBLE_ANNUAL_EUR else None

    out = df.copy()
    if "salary_raw" in out:
        codes = out.get("country_code")
        parsed = [
            _one(raw, codes.iloc[i] if codes is not None else None)
            for i, raw in enumerate(out["salary_raw"])
        ]
    else:
        parsed = None
    # Float dtype, so it sorts and sums as a number.
    out["salary_eur"] = pd.to_numeric(parsed, errors="coerce") if parsed is not None else pd.NA
    # ...and a text twin for grids. st.dataframe draws a missing number as a
    # grey "None", and on a column empty for nine postings in ten that read as
    # a value on almost every row. "—" reads as "not stated".
    out["salary"] = [
        "—" if pd.isna(v) else f"€{v:,.0f}" for v in pd.Series(out["salary_eur"], index=out.index)
    ]
    return out


# --- shared column_config ---------------------------------------------------
def posting_columns(**overrides) -> dict:
    """The house style for a postings table: link out, badge, money, dates.

    Every postings grid in the app uses this, so a column means the same thing
    on every page.
    """
    cols = {
        "title": st.column_config.TextColumn("Title", width="large"),
        "company_name": st.column_config.TextColumn("Company"),
        "market": st.column_config.TextColumn("Market"),
        "sponsorship": st.column_config.TextColumn(
            "Visa signal",
            help=(
                "Recognised sponsor = deterministic IND register match. "
                "Not yet classified = the LLM has not read this posting yet "
                "(which is not the same as 'no sponsorship')."
            ),
        ),
        "sponsor_kvk": st.column_config.TextColumn("KvK", help="Dutch company registry number."),
        "salary": st.column_config.TextColumn(
            "Salary (€/yr)",
            help=(
                "Annualised from the posting's raw salary text by the deterministic "
                "parser. — = not stated, or quoted in a non-EUR currency (no FX rate "
                "is invented here — see the raw text on the posting card)."
            ),
        ),
        "posted_at": st.column_config.DatetimeColumn("Posted", format="YYYY-MM-DD"),
        "last_seen_at": st.column_config.DatetimeColumn("Last seen", format="YYYY-MM-DD"),
        "source_url": st.column_config.LinkColumn(
            "Posting", display_text="open ↗", help="The original posting."
        ),
        "source": st.column_config.TextColumn("Source"),
    }
    cols.update(overrides)
    return cols


#: Default sort for every postings grid: recognised sponsors first, then most
#: recent. Stated once so no page quietly disagrees.
POSTINGS_ORDER = "is_recognised_sponsor desc, last_seen_at desc nulls last"

# Keep a stable name for the link colour used in markdown callouts.
LINK = RUST_700

# --- page chrome ------------------------------------------------------------
REPO_URL = "https://github.com/carlosdmv7/job-market-intelligence"
FAVICON = str(Path(__file__).with_name("assets") / "favicon.png")
_SUITE = "Job Market Intelligence"


def configure_page(page_title: str, *, layout: Literal["centered", "wide"] = "wide") -> None:
    """``st.set_page_config`` — must be the first Streamlit call on a page.

    Titles are suffixed with the product name so a pinned browser tab still
    says what the app is, and every page carries the brand favicon.
    """
    st.set_page_config(
        page_title=f"{page_title} · {_SUITE}",
        page_icon=FAVICON,
        layout=layout,
    )


def page_header(*, title: str, subtitle: str | None = None, freshness: bool = True) -> None:
    """Brand line + title + the live data-trust strip, in that order."""
    from streamlit_app import freshness as freshness_mod
    from streamlit_app.theme import render_header

    facts = freshness_mod.header_facts() if freshness else ()
    render_header(title=title, subtitle=subtitle, facts=facts)
    demo_notice()


def demo_notice() -> None:
    """Say so, on every page, when the data is the committed sample.

    Not a footnote: a dashboard that presents a frozen sample as if it were
    live is the precise dishonesty this project exists to avoid.
    """
    from streamlit_app.db import is_demo

    if not is_demo():
        return
    # Counted, not quoted. This banner's whole job is to stop a frozen sample
    # being read as live data, so a hardcoded row count that drifts from the
    # committed parquet would undermine the one claim it exists to make.
    from streamlit_app.db import run_df

    try:
        n = int(run_df("select count(*) as n from marts.FT_JOB_POSTING").iloc[0]["n"])
        size = f"{n:,} postings"
    except Exception:
        size = "a sample of postings"
    st.info(
        f"**Demo mode** — no warehouse configured, so this is a committed sample of "
        f"{size} frozen at export time, not live data. It is weighted toward open data "
        "roles so every page has something real to show; the live app reads the full "
        "corpus from MotherDuck, refreshed daily.",
        icon=":material/inventory_2:",
    )


def page_footer() -> None:
    from streamlit_app.theme import render_footer

    render_footer(repo_url=REPO_URL)
