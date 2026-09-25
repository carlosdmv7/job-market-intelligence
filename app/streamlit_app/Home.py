"""Entry point: what pages exist, in what order, where the nav sits.

Deliberately thin — each page file is a complete, independently runnable script
that calls its own ``ui.configure_page()`` and ``ui.page_header()``. This file
only decides the *shape* of navigation.

Why this file and not ``app.py``: Streamlit Community Cloud pins the main file
path in its own dashboard, outside the repo, and it points here. Putting the
navigation in a differently-named file meant the deployed app silently kept
rendering a single page with a sidebar. The entry point is whatever the host
launches, so the nav lives in the file the host launches.

``st.navigation`` also switches off the automatic ``pages/`` directory
discovery, so this mapping is the only source of nav order, labels and icons.
"""

from __future__ import annotations

import streamlit as st

# Flat: seven pages, each one click away. Dropdown groups ("Jobs", "Analyse",
# "How it works") hid five of the seven behind a second click, and a visitor
# skimming the bar saw three words, not what the app does. Same pattern as the
# sibling spanish-housing-radar app.
#
# Material Symbols, not emoji: they take the brand's ink instead of a font
# vendor's palette. Flags stay — they are data (which country), not decoration.
PAGES = [
    st.Page("pages/0_Overview.py", title="Overview", icon=":material/home:", default=True),
    st.Page("pages/1_Job_Explorer.py", title="Find Jobs", icon=":material/search:"),
    st.Page("pages/6_CV_Match.py", title="My Fit", icon=":material/target:"),
    st.Page("pages/2_Market_Trends.py", title="Market Trends", icon=":material/trending_up:"),
    # Market Trends compares the five markets; this one goes deep on one of
    # them. It absorbed the standalone Netherlands visa page: the IND register
    # cross-reference is a property of a single market, and giving it its own
    # nav entry made a five-country app read as a Dutch relocation tool. It now
    # renders as a section when NL is selected.
    st.Page("pages/3_Market_Detail.py", title="Market Detail", icon=":material/public:"),
    st.Page("pages/4_Ask_the_Data.py", title="Ask the Data", icon=":material/chat:"),
    st.Page("pages/5_How_It_Works.py", title="How it works", icon=":material/settings:"),
]

st.navigation(PAGES, position="top").run()
