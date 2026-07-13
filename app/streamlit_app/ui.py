"""Shared visual system for the Streamlit app.

One validated palette (dataviz skill) drives both the Streamlit chrome
(`.streamlit/config.toml`) and every Altair chart here, so the app reads as a
single system. Only current, supported APIs are used — `alt.theme.register`
(Altair 6) and `width="stretch"` (Streamlit) — no CSS injection, nothing on a
deprecation path.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import altair as alt
import streamlit as st

if TYPE_CHECKING:
    import pandas as pd

# --- palette (validated categorical order = CVD-safety) --------------------
CATEGORY = ["#2a78d6", "#1baf7a", "#eda100", "#eb6834", "#4a3aa7", "#e34948", "#e87ba4", "#008300"]
BLUE = "#2a78d6"
INK = "#0b0b0b"
INK_2 = "#52514e"
MUTED = "#898781"
GRID = "#e1e0d9"
AXIS = "#c3c2b7"
GOOD = "#0ca30c"
WARNING = "#fab219"
CRITICAL = "#d03b3b"
FONT = "system-ui, -apple-system, 'Segoe UI', sans-serif"

# Blue sequential ramp (ordinal/magnitude), from the reference palette.
BLUE_RAMP = ["#cde2fb", "#9ec5f4", "#6da7ec", "#3987e5", "#256abf", "#184f95", "#0d366b"]

# visa_status is ordered good -> bad; color is a *secondary* cue (labels always
# on the axis), so a diverging good/neutral/bad reading is safe here.
VISA_ORDER = ["explicit_yes", "likely_yes", "unclear", "likely_no", "explicit_no"]
VISA_COLORS = {
    "explicit_yes": GOOD,
    "likely_yes": "#1baf7a",
    "unclear": MUTED,
    "likely_no": WARNING,
    "explicit_no": CRITICAL,
}


@alt.theme.register("jmi", enable=True)
def _jmi_theme() -> alt.theme.ThemeConfig:
    return {
        "config": {
            "background": None,
            "font": FONT,
            "view": {"stroke": None},
            "axis": {
                "labelColor": INK_2,
                "titleColor": INK_2,
                "titleFontWeight": 600,
                "gridColor": GRID,
                "domainColor": AXIS,
                "tickColor": AXIS,
                "labelFontSize": 12,
                "titleFontSize": 12,
                "labelFont": FONT,
                "titleFont": FONT,
                "titlePadding": 8,
            },
            "legend": {
                "labelColor": INK_2,
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
                "subtitleColor": INK_2,
                "subtitleFontSize": 12,
            },
            "range": {"category": CATEGORY, "ramp": BLUE_RAMP},
            "bar": {"cornerRadiusEnd": 4},
            "mark": {"color": BLUE},
        }
    }


def show(chart: alt.Chart | alt.LayerChart) -> None:
    """Render an Altair chart full-width, using *our* theme (not Streamlit's)."""
    st.altair_chart(chart, width="stretch", theme=None)


def table(df: pd.DataFrame, **kwargs) -> None:
    st.dataframe(df, width="stretch", hide_index=True, **kwargs)


def hbar(
    df: pd.DataFrame,
    label: str,
    value: str,
    *,
    title: str | None = None,
    color: str = BLUE,
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
