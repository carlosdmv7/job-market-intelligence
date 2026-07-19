from __future__ import annotations

import pandas as pd
from streamlit_app.cv_match import (
    build_deep_dive_prompt,
    extract_skills,
    score_jobs,
    useful_vocabulary,
)

VOCAB = ["python", "dbt", "snowflake", "c++", "java", "airflow", ".net"]


def test_extract_skills_word_boundaries():
    cv = "Senior DE: Python, dbt and Snowflake. C++ in college. JavaScript on the side."
    found = extract_skills(cv, VOCAB)
    assert found == ["python", "dbt", "snowflake", "c++"]
    # "JavaScript" must NOT match "java"
    assert "java" not in found


def test_extract_skills_symbol_heavy_terms():
    assert extract_skills("worked with .NET daily", VOCAB) == [".net"]
    assert extract_skills("dotnet only", VOCAB) == []


def test_useful_vocabulary_drops_generic_terms():
    assert useful_vocabulary(["python", "Data", "AI", "dbt", "cloud"]) == ["python", "dbt"]


def test_score_jobs_tiebreak_prefers_more_evidence():
    jobs = pd.DataFrame(
        {
            "title": ["thin", "rich"],
            "technologies": [["python"], ["python", "dbt", "sql"]],
            "last_seen_at": pd.to_datetime(["2026-07-19"] * 2),
        }
    )
    ranked = score_jobs(jobs, ["python", "dbt", "sql"])
    assert list(ranked["title"]) == ["rich", "thin"]  # both 100%, more techs first


def test_score_jobs_overlap_and_na_safety():
    jobs = pd.DataFrame(
        {
            "title": ["perfect", "half", "none", "unenriched"],
            "technologies": [["python", "dbt"], ["python", "kafka"], ["kafka"], pd.NA],
            "last_seen_at": pd.to_datetime(["2026-07-19"] * 4),
        }
    )
    ranked = score_jobs(jobs, ["python", "dbt"])

    assert list(ranked["title"]) == ["perfect", "half", "none"]  # NA row dropped, sorted
    assert ranked.iloc[0]["match_pct"] == 1.0
    assert ranked.iloc[1]["match_pct"] == 0.5
    assert ranked.iloc[1]["missing"] == ["kafka"]
    assert ranked.iloc[2]["match_pct"] == 0.0


def test_deep_dive_prompt_truncates_and_includes_both_texts():
    prompt = build_deep_dive_prompt(
        "x" * 10_000,
        title="Data Engineer",
        company="Acme",
        description="y" * 10_000,
        technologies=["python"],
        max_chars=100,
    )
    assert "Data Engineer at Acme" in prompt
    assert "python" in prompt
    assert prompt.count("…[truncated]") == 2
    assert len(prompt) < 500
