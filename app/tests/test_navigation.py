"""The top-nav entry point: every page reachable, none crashing.

Runs against demo mode (CI has no warehouse), which is also the mode a
recruiter's first `make app` runs in — so this is the same path they hit.

``ENTRY`` is ``Home.py`` and must stay that way: Streamlit Community Cloud pins
the main file path in its own dashboard, outside this repo, and it points at
Home.py. Renaming the entry point silently reverts the deployed app to a
single-page sidebar layout, which is exactly what happened once already.
"""

from __future__ import annotations

from streamlit.testing.v1 import AppTest

ENTRY = "../streamlit_app/Home.py"

PAGE_PATHS = [
    "pages/0_Overview.py",
    "pages/1_Job_Explorer.py",
    "pages/2_Market_Trends.py",
    "pages/3_Market_Detail.py",
    "pages/4_Ask_the_Data.py",
    "pages/5_How_It_Works.py",
    "pages/6_CV_Match.py",
]


def test_home_renders_with_no_exception():
    at = AppTest.from_file(ENTRY, default_timeout=180)
    at.run()
    assert not at.exception


def test_every_page_is_reachable_from_the_top_nav():
    at = AppTest.from_file(ENTRY, default_timeout=180)
    at.run()
    for path in PAGE_PATHS:
        at.switch_page(path)
        at.run()
        assert not at.exception, f"{path} raised: {at.exception}"


def test_overview_page_links_point_at_registered_pages():
    # Cross-page links; a typo here 404s silently in the UI.
    at = AppTest.from_file(ENTRY, default_timeout=180)
    at.run()
    targets = {link.page for link in at.get("page_link")}
    assert targets == {"CV_Match", "Job_Explorer", "Market_Trends"}
