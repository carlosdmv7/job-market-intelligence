"""App-specific visual layer on top of the portable brand chrome.

Everything colour- or typography-related comes from :mod:`streamlit_app.theme`
(the drop-in shared file); this module adds only what is specific to *this*
domain — market labels, the visa vocabulary, and the chart helpers built on
them. Only current APIs: ``alt.theme`` (Altair 6) and ``width="stretch"``
(Streamlit), no CSS injection.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import altair as alt
import streamlit as st

from streamlit_app.theme import (
    AMBER_500,
    BORDER,
    INK,
    INK_MUTED,
    PETROL_900,
    RUST_500,
    RUST_700,
    SEQUENTIAL,
    SURFACE,
    TEAL_500,
    TEAL_700,
    show,
)

if TYPE_CHECKING:
    import pandas as pd

__all__ = [
    "MARKETS",
    "SPONSORSHIP_COLORS",
    "SPONSORSHIP_ORDER",
    "VISA_LABELS",
    "VISA_ORDER",
    "hbar",
    "market_label",
    "show",
    "sponsorship_bucket",
    "table",
]

# Re-exported so pages import their colours from one place.
PRIMARY = PETROL_900
ACCENT = RUST_500
GOOD = TEAL_700
MUTED = INK_MUTED
RAMP = SEQUENTIAL
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

SPONSORSHIP_ORDER = [RECOGNISED, LLM_ONLY, UNCLASSIFIED, NO_EVIDENCE]
SPONSORSHIP_COLORS = {
    RECOGNISED: TEAL_700,
    LLM_ONLY: TEAL_500,
    UNCLASSIFIED: INK_MUTED,
    NO_EVIDENCE: BORDER,
}

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


def sponsorship_scale() -> alt.Scale:
    return alt.Scale(
        domain=SPONSORSHIP_ORDER,
        range=[SPONSORSHIP_COLORS[s] for s in SPONSORSHIP_ORDER],
    )


def sponsorship_bucket(row) -> str:
    """Python mirror of :data:`SPONSORSHIP_SQL`, for already-fetched frames."""
    import pandas as pd

    if bool(row.get("is_recognised_sponsor")):
        return RECOGNISED
    if row.get("visa_status") in ("explicit_yes", "likely_yes"):
        return LLM_ONLY
    enriched = row.get("is_enriched")
    if enriched is None or pd.isna(enriched) or not enriched:
        return UNCLASSIFIED
    return NO_EVIDENCE


# --- the LLM's own 5-value read ---------------------------------------------
# visa_status is ordered good -> bad; colour is a *secondary* cue (labels are
# always on the axis), and the ramp is the brand's blue-orange diverging axis.
VISA_ORDER = ["explicit_yes", "likely_yes", "unclear", "likely_no", "explicit_no"]
VISA_COLORS = {
    "explicit_yes": TEAL_700,
    "likely_yes": TEAL_500,
    "unclear": INK_MUTED,
    "likely_no": AMBER_500,
    "explicit_no": RUST_500,
}
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


def visa_scale() -> alt.Scale:
    return alt.Scale(domain=VISA_ORDER, range=[VISA_COLORS[v] for v in VISA_ORDER])


#: Markets with a dedicated local corpus (flag + name for display); anything
#: else renders as its bare ISO code, NULL as Remote / global.
MARKETS = {
    "NL": "🇳🇱 Netherlands",
    "SE": "🇸🇪 Sweden",
    "DE": "🇩🇪 Germany",
    "ES": "🇪🇸 Spain",
}


def market_label(country_code: str | None) -> str:
    # `x != x` catches float NaN but *raises* on pd.NA, which DuckDB returns
    # for some nullable dtypes — so go through pd.isna instead.
    import pandas as pd

    if country_code is None or (pd.api.types.is_scalar(country_code) and pd.isna(country_code)):
        return "🌍 Remote / global"
    return MARKETS.get(country_code, country_code)


def table(df: pd.DataFrame, **kwargs) -> None:
    st.dataframe(df, width="stretch", hide_index=True, **kwargs)


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


def sponsorship_bar(
    df: pd.DataFrame,
    label: str,
    value: str,
    *,
    status: str = "sponsorship",
    value_title: str | None = None,
) -> alt.Chart:
    """Magnitude bars split by the four-bucket sponsorship roll-up."""
    return (
        alt.Chart(df)
        .mark_bar()
        .encode(
            y=alt.Y(f"{label}:N", sort="-x", title=None, axis=alt.Axis(labelLimit=240)),
            x=alt.X(f"{value}:Q", title=value_title, axis=alt.Axis(grid=True, tickCount=4)),
            color=alt.Color(f"{status}:N", scale=sponsorship_scale(), title=None),
            tooltip=[
                alt.Tooltip(f"{label}:N", title=label.replace("_", " ")),
                alt.Tooltip(f"{value}:Q", title=value_title or value.replace("_", " ")),
                alt.Tooltip(f"{status}:N", title="signal"),
            ],
        )
        .properties(height=max(160, df[label].nunique() * 30 + 12))
    )


# --- parsed salary ----------------------------------------------------------
#: Periods -> multiplier to a yearly figure. Days/hours use the Dutch full-time
#: norm (260 working days, 8h) — stated here rather than buried in a lambda.
_ANNUALISE = {"year": 1, "month": 12, "day": 260, "hour": 260 * 8}


def add_salary_eur(df: pd.DataFrame) -> pd.DataFrame:
    """Add ``salary_eur``: the raw salary text annualised, EUR only.

    Reuses the deterministic parser from ``jmi_enrichment`` (the same tested
    contract the pipeline documents) rather than re-implementing it in SQL.
    Non-EUR postings are left null on purpose: converting them would mean
    inventing an FX rate and a rate date, and this app does not do that.
    """
    import pandas as pd

    from jmi_enrichment.salary import parse_salary

    def _one(raw) -> float | None:
        if raw is None or (pd.api.types.is_scalar(raw) and pd.isna(raw)):
            return None
        parsed = parse_salary(str(raw))
        if parsed is None or parsed.currency != "EUR":
            return None
        amount = parsed.max_amount or parsed.min_amount
        if amount is None:
            return None
        factor = _ANNUALISE.get(str(parsed.period) if parsed.period else "year")
        return round(amount * factor) if factor else None

    out = df.copy()
    parsed = out["salary_raw"].map(_one) if "salary_raw" in out else None
    # Force a float dtype: an object column of Nones renders as the literal
    # string "None" in st.dataframe, which reads as a value rather than as the
    # absence of one.
    out["salary_eur"] = pd.to_numeric(parsed, errors="coerce") if parsed is not None else pd.NA
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
        "salary_eur": st.column_config.NumberColumn(
            "Salary (€/yr)",
            format="euro",
            help=(
                "Annualised from the posting's raw salary text by the deterministic "
                "parser. Blank = not stated, or quoted in a non-EUR currency (no FX "
                "rate is invented here — see the raw text on the posting card)."
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
INK_COLOR = INK

# --- page chrome ------------------------------------------------------------
REPO_URL = "https://github.com/carlosdmv7/job-market-intelligence"
FAVICON = str(Path(__file__).with_name("assets") / "favicon.png")
_SUITE = "Job Market Intelligence"


def configure_page(page_title: str, *, layout: str = "wide") -> None:
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


def page_footer() -> None:
    from streamlit_app.theme import render_footer

    render_footer(
        repo_url=REPO_URL,
        note=(
            "Every figure on this page is queried from the MotherDuck marts at page load. "
            "Nothing here is hardcoded."
        ),
    )
