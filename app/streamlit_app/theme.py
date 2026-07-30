"""Shared brand chrome — the file that makes my apps read as one product.

This module is **portable by contract**: it imports nothing from this project,
so it can be dropped into any of my Streamlit apps unchanged. Anything
app-specific (warehouse queries, domain vocabularies) belongs in the caller,
which passes the results in as :class:`Fact` values.

Two hard rules, kept from the existing app:

* **Native keys only** — the page chrome comes from ``.streamlit/config.toml``
  and the charts from ``alt.theme``. No ``<style>`` injection anywhere, so a
  Streamlit upgrade can never silently break the look.
* **Tokens are the single source of truth** — the hex values below are the same
  ones in ``config.toml`` and on the portfolio site. Never hardcode a colour at
  a call site; import it from here.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

import altair as alt
import streamlit as st

if TYPE_CHECKING:
    from collections.abc import Sequence

# --- brand tokens -----------------------------------------------------------
SAND_100 = "#F6E2B3"
AMBER_500 = "#E7A84E"
RUST_500 = "#D96C2C"
TEAL_500 = "#3E8E7E"
PETROL_900 = "#274C56"

# Derived — required, do not substitute.
SURFACE = "#FDFAF4"  # page background
SURFACE_2 = "#F5EFE3"  # cards, sidebar
BORDER = "#E4D9C4"  # hairlines
INK = "#274C56"  # body text
INK_MUTED = "#5C7480"  # secondary text
RUST_700 = "#A8501F"  # links, primary button fill (white label)
TEAL_700 = "#2E6B5E"  # success, secondary button fill (white label)
RUST_050 = "#FBEADF"
TEAL_050 = "#E4F0EC"

FONT = "sans-serif"

# --- chart scales -----------------------------------------------------------
#: Max 5 categories. More than that and the chart should aggregate instead —
#: a sixth colour is a design error, not a missing token.
CATEGORICAL = [PETROL_900, RUST_500, TEAL_500, AMBER_500, INK_MUTED]

#: Any over/under measure. Blue-orange axis, so it survives deuteranopia and
#: protanopia; never substitute a green→red ramp.
DIVERGING = [TEAL_700, "#7FB3A4", SAND_100, AMBER_500, RUST_500]

#: Counts, density, trend heat.
SEQUENTIAL = [SAND_100, AMBER_500, RUST_500, RUST_700, "#6E2F10"]

#: Contrast rules worth encoding rather than remembering: these two are fill-
#: and large-text-only against SURFACE (3.4:1 and 3.9:1), and AMBER_500 (2.1:1)
#: is never text. Use RUST_700 / TEAL_700 whenever a colour carries words.
LINK = RUST_700
SUCCESS = TEAL_700
ACCENT = RUST_500

PORTFOLIO_URL = "https://carlosdmv7.github.io/personal-portfolio/"
AUTHOR = "Carlos De Manuel"
AUTHOR_ROLE = "Analytics Engineer"

Tone = Literal["neutral", "good", "warn", "bad"]

#: Streamlit's native markdown colour names — the only text colouring used
#: here, since brand hexes in markdown would mean CSS injection.
_TONE_COLOR: dict[str, str] = {"good": "green", "warn": "orange", "bad": "red"}


@dataclass(frozen=True, slots=True)
class Fact:
    """One cell of the freshness strip.

    ``value`` is pre-formatted by the caller: this module never guesses how a
    number should read.
    """

    label: str
    value: str
    tone: Tone = "neutral"
    help: str | None = None

    def markdown(self) -> str:
        color = _TONE_COLOR.get(self.tone)
        value = f":{color}[**{self.value}**]" if color else f"**{self.value}**"
        return f"{value} {self.label}"


@alt.theme.register("carlos-brand", enable=True)
def _brand_theme() -> alt.theme.ThemeConfig:
    """Altair config built from the tokens above — the charts' half of the brand."""
    return {
        "config": {
            "background": "transparent",  # inherit the Streamlit surface
            "font": FONT,
            "view": {"stroke": None},
            "axis": {
                "labelColor": INK_MUTED,
                "titleColor": INK_MUTED,
                "titleFontWeight": 600,
                "gridColor": BORDER,
                "domainColor": BORDER,
                "tickColor": BORDER,
                "labelFontSize": 12,
                "titleFontSize": 12,
                "labelFont": FONT,
                "titleFont": FONT,
                "titlePadding": 8,
            },
            "legend": {
                "labelColor": INK_MUTED,
                "titleColor": INK,
                "titleFontWeight": 600,
                "labelFont": FONT,
                "titleFont": FONT,
                "labelFontSize": 12,
                "symbolType": "circle",
                "orient": "top",
                "offset": 6,
            },
            "title": {
                "color": INK,
                "font": FONT,
                "fontSize": 15,
                "fontWeight": 700,
                "anchor": "start",
                "subtitleColor": INK_MUTED,
                "subtitleFontSize": 12,
            },
            "range": {
                "category": CATEGORICAL,
                "diverging": DIVERGING,
                "heatmap": SEQUENTIAL,
                "ramp": SEQUENTIAL,
            },
            "bar": {"cornerRadiusEnd": 4},
            "mark": {"color": PETROL_900},
        }
    }


def show(chart: alt.Chart | alt.LayerChart | alt.VConcatChart | alt.HConcatChart) -> None:
    """Render full-width with *our* theme (``theme=None`` disables Streamlit's)."""
    st.altair_chart(chart, width="stretch", theme=None)


def render_header(
    *,
    title: str | None = None,
    subtitle: str | None = None,
    facts: Sequence[Fact] = (),
) -> None:
    """Brand line, optional page title, and the freshness strip.

    The identity line is deliberately the first thing on every page: these apps
    are portfolio pieces, so the byline and the way back to the portfolio are
    part of the product.
    """
    st.caption(f"**{AUTHOR}** · {AUTHOR_ROLE} · [← portfolio]({PORTFOLIO_URL})")
    if title:
        st.title(title)
    if subtitle:
        st.caption(subtitle)
    if facts:
        render_freshness(facts)


def render_freshness(facts: Sequence[Fact]) -> None:
    """The data-trust strip: every number here is read live, never hardcoded.

    Rendered as one caption line rather than a metric row so it reads as
    provenance (a byline for the data) instead of competing with the page's
    actual metrics.
    """
    if not facts:
        return
    st.caption(" &nbsp;·&nbsp; ".join(f.markdown() for f in facts))
    with_help = [f for f in facts if f.help]
    if with_help:
        with st.expander("What these numbers mean"):
            for f in with_help:
                st.markdown(f"- **{f.value}** {f.label} — {f.help}")


def render_footer(*, repo_url: str | None = None, note: str | None = None) -> None:
    """Closing rule + provenance line. Mirrors the portfolio site's footer."""
    st.divider()
    parts = [f"**{AUTHOR}** · {AUTHOR_ROLE}", f"[Portfolio]({PORTFOLIO_URL})"]
    if repo_url:
        parts.append(f"[Source]({repo_url})")
    st.caption(" · ".join(parts))
    if note:
        st.caption(note)
