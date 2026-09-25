"""The reloader that keeps a Cloud redeploy from running new pages on old helpers."""

from __future__ import annotations

import importlib
import os
import sys
import time
from pathlib import Path

import pytest
from streamlit_app import hot_reload

ROOT = Path(__file__).resolve().parents[2]
THEME = ROOT / "app" / "streamlit_app" / "theme.py"


@pytest.fixture
def clean_state():
    # drop_stale removes every repo module, so put every one of them back — and
    # remove any the test added. A module swapped under the other test files
    # would reproduce the very bug this guards against.
    saved = {name: sys.modules[name] for name in hot_reload._repo_modules(ROOT)}
    had_state = hasattr(sys, hot_reload._STATE_ATTR)
    old_state = getattr(sys, hot_reload._STATE_ATTR, None)
    yield
    for name in hot_reload._repo_modules(ROOT):
        if name not in saved:
            sys.modules.pop(name, None)
    sys.modules.update(saved)
    if had_state:
        setattr(sys, hot_reload._STATE_ATTR, old_state)
    elif hasattr(sys, hot_reload._STATE_ATTR):
        delattr(sys, hot_reload._STATE_ATTR)


def _bump(path: Path, to: float):
    stat = path.stat()
    os.utime(path, (stat.st_atime, to))
    return stat


@pytest.mark.usefixtures("clean_state")
def test_one_changed_file_drops_every_repo_module():
    for name in ("streamlit_app.theme", "streamlit_app.ui", "streamlit_app.charts"):
        importlib.import_module(name)
    hot_reload.drop_stale(ROOT)  # first run of the process: drop + record
    for name in ("streamlit_app.theme", "streamlit_app.ui", "streamlit_app.charts"):
        importlib.import_module(name)
    assert hot_reload.drop_stale(ROOT) == []  # nothing changed, nothing dropped

    stat = _bump(THEME, THEME.stat().st_mtime + 5)  # the pull rewrote theme.py only
    try:
        dropped = set(hot_reload.drop_stale(ROOT))
    finally:
        os.utime(THEME, (stat.st_atime, stat.st_mtime))
    # ui and charts did not change, but they hold theme's objects.
    assert {"streamlit_app.theme", "streamlit_app.ui", "streamlit_app.charts"} <= dropped


@pytest.mark.usefixtures("clean_state")
def test_a_pull_before_the_second_run_is_still_seen():
    if hasattr(sys, hot_reload._STATE_ATTR):
        delattr(sys, hot_reload._STATE_ATTR)
    sys.modules.pop("streamlit_app.theme", None)
    hot_reload.drop_stale(ROOT)
    importlib.import_module("streamlit_app.theme")  # imported after the drop: no baseline

    stat = _bump(THEME, time.time() + 5)  # the pull lands now
    try:
        assert "streamlit_app.theme" in hot_reload.drop_stale(ROOT)
    finally:
        os.utime(THEME, (stat.st_atime, stat.st_mtime))


@pytest.mark.usefixtures("clean_state")
def test_the_reloader_and_installed_packages_are_left_alone():
    hot_reload.drop_stale(ROOT)
    assert "streamlit_app.hot_reload" in sys.modules
    assert "streamlit" in sys.modules
    assert "pandas" in sys.modules
