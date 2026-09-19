"""The top-nav entry point: every page reachable, none crashing.

Runs against demo mode (CI has no warehouse), which is also the mode a
recruiter's first `make app` runs in — so this is the same path they hit.

``ENTRY`` is ``Home.py`` and must stay that way: Streamlit Community Cloud pins
the main file path in its own dashboard, outside this repo, and it points at
Home.py. Renaming the entry point silently reverts the deployed app to a
single-page sidebar layout, which is exactly what happened once already.
"""

from __future__ import annotations

import pytest
from streamlit.testing.v1 import AppTest
from streamlit_app import db

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


@pytest.fixture(autouse=True)
def demo_mode(monkeypatch):
    """Force the committed-sample path for every test in this file.

    Without this, a developer with a .env exercises the live warehouse while CI
    — which has no credentials — exercises demo mode, so the two run different
    code and only one of them fails. That is exactly how a page querying
    `staging` (absent from the demo sample) passed locally and broke the build:
    the schema exists on a real warehouse and nowhere else.

    Demo mode is also what a recruiter's first `make app` runs, so it is the
    path that most deserves the coverage.
    """
    monkeypatch.delenv("motherduck_token", raising=False)
    monkeypatch.setenv("JMI_DUCKDB_DATABASE", "/nonexistent/no-warehouse-here.duckdb")
    from jmi_core.settings import get_settings

    get_settings.cache_clear()
    db._live_connection.clear()
    db.staging_available.clear()
    yield
    get_settings.cache_clear()
    db._live_connection.clear()
    db.staging_available.clear()


def test_the_suite_really_is_in_demo_mode():
    """Guard the guard: if this stops holding, the tests below stop meaning much."""
    assert db.is_demo(), "expected the committed sample, not a live warehouse"


def test_staging_is_absent_from_the_demo_sample():
    """The fact that broke the build, pinned.

    Descriptions are megabytes and a committed file here is capped at 512 KB,
    so the sample ships the marts only. Every page reading `staging` must ask
    this first; three of them were not, and two of those hid behind a click
    (a selected row, a pressed button) where no test could reach them.
    """
    assert db.staging_available() is False


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
