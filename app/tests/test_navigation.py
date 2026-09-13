"""The top-nav entry point: every page reachable, none crashing.

Runs against demo mode (CI has no warehouse), which is also the mode a
recruiter's first `make app` runs in — so this is the same path they hit.
"""

from __future__ import annotations

from streamlit.testing.v1 import AppTest

ENTRY = "../streamlit_app/app.py"

PAGE_PATHS = [
    "pages/1_Job_Explorer.py",
    "pages/2_Market_Trends.py",
    "pages/3_NL_Visa_Audit.py",
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


def test_home_page_link_points_at_a_registered_page():
    # The one cross-page link in the app; a typo here 404s silently in the UI.
    at = AppTest.from_file(ENTRY, default_timeout=180)
    at.run()
    links = at.get("page_link")
    assert len(links) == 1
    assert links[0].page == "NL_Visa_Audit"
