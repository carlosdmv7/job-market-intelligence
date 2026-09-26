"""The daily flow's source list against the scraper registry."""

from __future__ import annotations

from jmi_flows.daily import SOURCES, source_label
from jmi_scrapers.registry import SCRAPERS

#: Registered but deliberately not run daily.
NOT_RUN_DAILY = {"honeypot"}


def test_every_operational_scraper_runs_daily():
    # A scraper added to the registry but not to SOURCES would be tested,
    # documented, and never run — the pipeline would simply not know about it.
    assert {source for source, _ in SOURCES} == set(SCRAPERS) - NOT_RUN_DAILY


def test_adzuna_runs_once_per_market():
    assert sorted(c for s, c in SOURCES if s == "adzuna") == ["de", "es", "nl"]


def test_task_labels_are_unique():
    labels = [source_label(s, c) for s, c in SOURCES]
    assert len(labels) == len(set(labels))
