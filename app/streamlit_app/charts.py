"""Chart builders for the Overview — the stack mix by market and the daily flow.

Each returns an Altair chart; ``theme.show`` renders it with the brand theme.
Colour carries meaning only: the heat ramp is the brand's sequential scale, and
the daily bars are petrol with the pipeline's partial sweeps drawn as hairline
grey so they read as missing data, not as a quiet day.
"""

from __future__ import annotations

import altair as alt
import pandas as pd

from streamlit_app.theme import BORDER, INK, INK_MUTED, PETROL_900, RUST_500, SEQUENTIAL


def heatmap_stack_mix(df: pd.DataFrame, markets: list[str]) -> alt.LayerChart:
    """Technologies x markets, each cell that market's share of stack mentions.

    ``df`` has one row per (market, tech) with ``share`` in 0-1. Shares are
    *within* a market — each column sums to 100% across all its technologies —
    because the markets are read at very different depths: Adzuna returns a
    snippet of each posting and the LLM finds ~2 technologies in it, where
    Sweden's JobTech feed carries the full text and ~7. Raw counts made the
    all-markets stack ranking a ranking of Sweden. A column's mix compares
    fairly whatever the depth.
    """
    order = df.groupby("tech")["share"].sum().sort_values(ascending=False).index.tolist()
    top = df["share"].max()
    d = df.assign(
        pct=lambda x: [f"{s:.0%}" if s >= 0.005 else "" for s in x["share"]],
        # White only on the dark end of the ramp; ink everywhere else.
        dark=lambda x: x["share"] >= top * 0.62,
    )
    base = alt.Chart(d).encode(
        x=alt.X(
            "market:N",
            sort=markets,
            title=None,
            axis=alt.Axis(orient="top", labelAngle=0, labelFontSize=13, domain=False, ticks=False),
        ),
        y=alt.Y("tech:N", sort=order, title=None, axis=alt.Axis(domain=False, ticks=False)),
    )
    cells = base.mark_rect(cornerRadius=3, stroke="#FDFAF4", strokeWidth=2).encode(
        color=alt.Color(
            "share:Q",
            scale=alt.Scale(range=SEQUENTIAL[:4], domain=[0, top]),
            legend=None,
        ),
        tooltip=[
            alt.Tooltip("market:N", title="Market"),
            alt.Tooltip("tech:N", title="Technology"),
            alt.Tooltip("share:Q", title="Share of its stack mentions", format=".1%"),
            alt.Tooltip("mentions:Q", title="Mentions"),
        ],
    )
    labels = base.mark_text(fontSize=12).encode(
        text="pct:N",
        color=alt.condition("datum.dark", alt.value("white"), alt.value(INK)),
    )
    return (cells + labels).properties(height=max(260, 30 * len(order)))


def bar_daily_new_roles(df: pd.DataFrame) -> alt.LayerChart:
    """New data roles first seen each day, with a 7-day average over it.

    ``df``: ``day``, ``new_roles``, ``partial`` (bool). A partial sweep — a day
    the pipeline tracked far fewer postings than usual — is drawn in the border
    colour and left out of the average: its low count is the scraper's, not
    the market's.
    """
    d = df.assign(kind=lambda x: x["partial"].map({True: "Partial sweep", False: "New roles"}))
    bars = (
        alt.Chart(d)
        .mark_bar(width={"band": 0.75}, cornerRadiusEnd=2)
        .encode(
            x=alt.X("day:T", title=None, axis=alt.Axis(format="%-d %b", tickCount=8, grid=False)),
            y=alt.Y("new_roles:Q", title=None, axis=alt.Axis(tickCount=4)),
            color=alt.Color(
                "kind:N",
                scale=alt.Scale(domain=["New roles", "Partial sweep"], range=[PETROL_900, BORDER]),
                legend=alt.Legend(title=None, orient="top-left", direction="horizontal"),
            ),
            tooltip=[
                alt.Tooltip("day:T", title="Day", format="%a %-d %b"),
                alt.Tooltip("new_roles:Q", title="New roles"),
                alt.Tooltip("kind:N", title=""),
            ],
        )
    )
    line = (
        alt.Chart(d[~d["partial"]])
        .mark_line(color=RUST_500, strokeWidth=2.5, interpolate="monotone")
        .encode(
            x="day:T",
            y="avg7:Q",
            tooltip=[alt.Tooltip("avg7:Q", title="7-day average", format=".0f")],
        )
    )
    label = (
        alt.Chart(d[~d["partial"]].tail(1))
        .mark_text(align="left", dx=6, color=INK_MUTED, fontSize=12)
        .encode(x="day:T", y="avg7:Q", text=alt.Text("avg7:Q", format=".0f"))
    )
    return (bars + line + label).properties(height=220)
