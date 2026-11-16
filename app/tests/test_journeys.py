"""The paths a visitor actually walks, across pages and behind buttons.

``test_navigation`` proves every page renders. These drive the two flows whose
bugs hid behind an interaction: a CV that has to survive leaving the page it
was entered on, and a question whose SQL comes from a model that may have been
talked into anything.
"""

from __future__ import annotations

import pytest
from streamlit.testing.v1 import AppTest
from streamlit_app import db, limits

ENTRY = "../streamlit_app/Home.py"
CV = "Data engineer. Python, SQL, dbt, Airflow, Snowflake, AWS, Docker, Spark."


@pytest.fixture(autouse=True)
def demo_mode(monkeypatch):
    """The committed sample, for the reasons given in test_navigation."""
    monkeypatch.delenv("motherduck_token", raising=False)
    monkeypatch.setenv("JMI_DUCKDB_DATABASE", "/nonexistent/no-warehouse-here.duckdb")
    from jmi_core.settings import get_settings

    get_settings.cache_clear()
    db._live_connection.clear()
    db.staging_available.clear()
    limits._app_budget.clear()
    yield
    get_settings.cache_clear()
    db._live_connection.clear()
    db.staging_available.clear()
    limits._app_budget.clear()


class _Scripted:
    """A provider that answers with whatever SQL the test hands it."""

    model = "scripted"

    def __init__(self, reply: str) -> None:
        self.reply = reply
        self.calls = 0

    def complete(self, *, system: str, user: str) -> str:
        self.calls += 1
        return self.reply


def _app() -> AppTest:
    at = AppTest.from_file(ENTRY, default_timeout=180)
    at.run()
    return at


def _texts(at: AppTest) -> str:
    return " ".join(str(el.value) for el in [*at.caption, *at.markdown])


# --- the CV follows you -------------------------------------------------------
def test_a_cv_entered_on_my_fit_survives_a_trip_to_find_jobs():
    at = _app()
    at.switch_page("pages/6_CV_Match.py").run()
    at.text_area[0].set_value(CV).run()
    assert not at.exception
    assert len(at.dataframe) == 1, "the ranked list should render once a CV is in"
    assert "python" in [s.lower() for s in at.session_state["cv_skills"]]

    # Find Jobs picks the skills up: a fit column, and a way to sort by it.
    at.switch_page("pages/1_Job_Explorer.py").run()
    assert not at.exception
    sort = next(s for s in at.selectbox if s.label == "Sort by")
    assert "My fit" in sort.options
    assert "match" in at.dataframe[0].value.columns
    sort.select("My fit").run()
    assert not at.exception
    scores = at.dataframe[0].value["match"].dropna().tolist()
    assert scores == sorted(scores, reverse=True) and scores, "best fit first"

    # ...and coming back does not ask for the CV again.
    at.switch_page("pages/6_CV_Match.py").run()
    assert not at.exception
    assert at.text_area[0].value in ("", None), "the widget itself was reset by the trip"
    assert len(at.dataframe) == 1, "but the ranking is rebuilt from the session's CV"


def test_forgetting_the_cv_removes_every_trace_of_it():
    at = _app()
    at.switch_page("pages/6_CV_Match.py").run()
    at.text_area[0].set_value(CV).run()
    next(b for b in at.button if b.label == "Forget my CV").click().run()
    assert not at.exception
    for key in ("cv_text", "cv_skills", "fit_answers"):
        assert key not in at.session_state
    assert len(at.dataframe) == 0


def test_find_jobs_without_a_cv_offers_no_fit_column():
    at = _app()
    at.switch_page("pages/1_Job_Explorer.py").run()
    assert "match" not in at.dataframe[0].value.columns
    assert "My fit" not in next(s for s in at.selectbox if s.label == "Sort by").options


def test_find_jobs_reports_the_real_count_and_an_honest_empty_state():
    at = _app()
    at.switch_page("pages/1_Job_Explorer.py").run()
    shown = len(at.dataframe[0].value)
    assert f"**{shown:,}** matching" in _texts(at) or "showing the first" in _texts(at)

    at.text_input[0].set_value("zzz-no-posting-says-this").run()
    assert not at.exception
    assert len(at.dataframe) == 0
    assert any("Nothing matches" in str(i.value) for i in at.info)


# --- the question is a stranger's ----------------------------------------------
def _ask(at: AppTest, question: str = "anything") -> AppTest:
    at.text_input[0].set_value(question)
    next(b for b in at.button if b.label == "Ask").click()
    return at.run()


@pytest.mark.parametrize(
    "reply",
    [
        "select current_setting('motherduck_token')",
        "select content from read_text('/proc/self/environ')",
        "select * from raw.raw_job_postings",
        "drop table marts.FT_JOB_POSTING",
    ],
)
def test_a_model_talked_into_hostile_sql_gets_a_refusal_not_a_result(monkeypatch, reply):
    monkeypatch.setattr("jmi_enrichment.providers.get_provider", lambda _s: _Scripted(reply))
    at = _app()
    at.switch_page("pages/4_Ask_the_Data.py").run()
    _ask(at)
    assert not at.exception
    assert len(at.dataframe) == 0
    assert any("did not produce a query I can run" in str(e.value) for e in at.error)


def test_a_good_question_is_answered_and_the_answer_survives_a_rerun(monkeypatch):
    provider = _Scripted(
        "select country_code, count(*) as roles from marts.FT_JOB_POSTING group by 1 order by 2 desc"
    )
    monkeypatch.setattr("jmi_enrichment.providers.get_provider", lambda _s: provider)
    at = _app()
    at.switch_page("pages/4_Ask_the_Data.py").run()
    _ask(at, "roles per country")
    assert not at.exception and not at.error
    assert len(at.dataframe) == 1
    assert "LIMIT 200" in at.code[0].value

    at.run()  # any rerun: a sort, a tooltip
    assert len(at.dataframe) == 1, "the answer is kept, not re-asked"
    assert provider.calls == 1


def test_llm_calls_are_rationed_per_visitor(monkeypatch):
    provider = _Scripted("select 1 as n from marts.DT_DATE")
    monkeypatch.setattr("jmi_enrichment.providers.get_provider", lambda _s: provider)
    monkeypatch.setenv("JMI_APP_LLM_CALLS_PER_DAY", "100")
    at = _app()
    at.switch_page("pages/4_Ask_the_Data.py").run()
    for _ in range(limits.PER_SESSION + 2):
        _ask(at)
    assert provider.calls == limits.PER_SESSION
    assert any("used this session" in str(e.value) for e in at.error)


def test_the_shared_daily_budget_stops_everyone(monkeypatch):
    provider = _Scripted("select 1 as n from marts.DT_DATE")
    monkeypatch.setattr("jmi_enrichment.providers.get_provider", lambda _s: provider)
    monkeypatch.setenv("JMI_APP_LLM_CALLS_PER_DAY", "1")
    first = _app()
    first.switch_page("pages/4_Ask_the_Data.py").run()
    _ask(first)
    second = _app()  # a different visitor
    second.switch_page("pages/4_Ask_the_Data.py").run()
    _ask(second)
    assert provider.calls == 1
    assert any("shared LLM budget is spent" in str(e.value) for e in second.error)
