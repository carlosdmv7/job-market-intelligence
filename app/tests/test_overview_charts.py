"""The Overview's two charts: the stack mix and the daily flow."""

from __future__ import annotations

import pandas as pd
from streamlit_app.charts import bar_daily_new_roles, heatmap_stack_mix


def _layer_data(spec: dict, i: int) -> list[dict]:
    """Rows of layer ``i``, whichever dataset name Altair gave them."""
    name = spec["layer"][i]["data"]["name"]
    return spec["datasets"][name]


def test_heatmap_keeps_every_market_as_a_column_in_the_given_order():
    mix = pd.DataFrame(
        {
            "market": ["🇪🇸 Spain", "🇪🇸 Spain", "🇸🇪 Sweden", "🇸🇪 Sweden"],
            "tech": ["python", "sql", "python", "sql"],
            "mentions": [3, 1, 60, 40],
            "share": [0.75, 0.25, 0.6, 0.4],
        }
    )
    spec = heatmap_stack_mix(mix, ["🇸🇪 Sweden", "🇪🇸 Spain"]).to_dict()
    assert spec["layer"][0]["encoding"]["x"]["sort"] == ["🇸🇪 Sweden", "🇪🇸 Spain"]
    # White labels only at the dark end of the ramp.
    dark = {(r["market"], r["tech"]): r["dark"] for r in spec["datasets"][spec["data"]["name"]]}
    assert dark[("🇪🇸 Spain", "python")] is True
    assert dark[("🇪🇸 Spain", "sql")] is False


def test_partial_sweeps_stay_out_of_the_average():
    days = pd.date_range("2026-09-01", periods=10, freq="D")
    daily = pd.DataFrame(
        {
            "day": days,
            "new_roles": [50] * 10,
            "partial": [False] * 5 + [True] + [False] * 4,
            "avg7": [50.0] * 10,
        }
    )
    spec = bar_daily_new_roles(daily).to_dict()
    line_rows = _layer_data(spec, 1)
    assert len(line_rows) == 9
    assert all(not r["partial"] for r in line_rows)
