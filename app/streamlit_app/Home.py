"""Entry point: what pages exist, how they're grouped, where the nav sits.

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

PAGES = {
    "": [st.Page("pages/0_Overview.py", title="Overview", icon="🧭", default=True)],
    "Jobs": [
        st.Page("pages/1_Job_Explorer.py", title="Find Jobs", icon="🔎"),
        st.Page("pages/6_CV_Match.py", title="My Fit", icon="🎯"),
    ],
    "Analyse": [
        st.Page("pages/2_Market_Trends.py", title="Market Trends", icon="📈"),
        st.Page("pages/4_Ask_the_Data.py", title="Ask the Data", icon="💬"),
    ],
    # The visa cross-reference is a showcase of deterministic-vs-LLM signal, not
    # a daily-use page: the user is an EU citizen and needs no sponsorship, and
    # only 1 posting in 730 states it explicitly. It reads as engineering
    # evidence, so it sits with the engineering pages.
    "How it works": [
        st.Page("pages/5_How_It_Works.py", title="Pipeline & Evals", icon="⚙️"),
        st.Page("pages/3_NL_Visa_Audit.py", title="Visa Signal (NL)", icon="🛂"),
    ],
}

st.navigation(PAGES, position="top").run()
