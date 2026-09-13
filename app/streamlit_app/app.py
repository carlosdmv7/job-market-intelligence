"""Entry point: what pages exist, how they're grouped, where the nav sits.

Deliberately thin. Each page file is still a complete, independently runnable
script — it calls its own ``ui.configure_page()`` (so the browser tab title
stays specific to that page) and its own ``ui.page_header()``. This file only
decides the *shape* of navigation.

Moved off the sidebar (Streamlit's old default for multipage apps) onto a top
bar: with six pages plus Home, a left rail was the first thing competing for
attention, and grouping by task made "which of these seven names do I click"
into three visible categories instead.

Using ``st.navigation`` here means the ``pages/`` directory's automatic
sidebar discovery is not used — this mapping is the only source of nav order,
labels and icons.
"""

from __future__ import annotations

import streamlit as st

PAGES = {
    "": [st.Page("Home.py", title="Home", icon="🧭", default=True)],
    "Explore": [
        st.Page("pages/1_Job_Explorer.py", title="Job Explorer", icon="🔎"),
        st.Page("pages/2_Market_Trends.py", title="Market Trends", icon="📈"),
        st.Page("pages/3_NL_Visa_Audit.py", title="NL Visa Audit", icon="🛂"),
    ],
    "Tools": [
        st.Page("pages/4_Ask_the_Data.py", title="Ask the Data", icon="💬"),
        st.Page("pages/6_CV_Match.py", title="CV Match", icon="🎯"),
    ],
    "About": [
        st.Page("pages/5_How_It_Works.py", title="How It Works", icon="⚙️"),
    ],
}

st.navigation(PAGES, position="top").run()
