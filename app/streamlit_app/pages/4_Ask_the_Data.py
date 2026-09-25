"""Ask the Data — controlled text-to-SQL over the marts (SELECT-only guard)."""

from __future__ import annotations

import streamlit as st
from streamlit_app import ui
from streamlit_app.agent import build_sql
from streamlit_app.db import require_marts, run_df

from jmi_core.settings import get_settings
from jmi_enrichment.providers import get_provider

ui.configure_page("Ask the Data")
ui.page_header(
    title="Ask the Data",
    subtitle="Ask a question in plain English. An LLM writes the SQL; you get to read it first.",
)
st.markdown(
    "Useful when the question you have isn't one of the filters — *\"which companies hire "
    'for dbt in Spain but not in Germany?"*. **The generated SQL is always shown**, so you '
    "can check it rather than trust it, and it is rejected unless it is a single read-only "
    "query against the published tables."
)

require_marts(
    "marts.FT_JOB_POSTING",
    missing="Connected, but no marts yet — run the pipeline, then `make dbt-build`.",
)

settings = get_settings()
st.caption(
    f"One LLM call per question, on a free tier (`{settings.llm_provider}` / "
    f"`{settings.llm_model}`) — if the daily quota is spent you will get an error."
)

examples = [
    "Which technologies are most in demand in Spain?",
    "Compare open data roles per country",
    "Top 10 technologies in Sweden vs the Netherlands",
    "Companies hiring Data Engineers where English is sufficient",
]

if "ask_q" not in st.session_state:
    st.session_state.ask_q = examples[0]

st.write("**Try one:**")
cols = st.columns(2)
for i, ex in enumerate(examples):
    if cols[i % 2].button(ex, width="stretch"):
        st.session_state.ask_q = ex

question = st.text_input("Your question", key="ask_q")
go = st.button("Ask", type="primary")

if go and question.strip():
    with st.spinner("Generating SQL…"):
        try:
            sql = build_sql(question, get_provider(settings))
        except Exception as exc:
            st.error(f"Could not generate a safe query: {exc}")
            st.stop()

    st.code(sql, language="sql")
    with st.spinner("Running query…"):
        try:
            df = run_df(sql)
        except Exception as exc:
            st.error(f"Query failed: {exc}")
            st.stop()

    st.success(f"{len(df):,} rows")

    # Auto-chart a clean 2-column (label, measure) result.
    numeric = df.select_dtypes("number")
    if df.shape[1] == 2 and numeric.shape[1] == 1 and 1 <= len(df) <= 30:
        label = next(c for c in df.columns if c not in numeric.columns)
        value = numeric.columns[0]
        ui.show(ui.hbar(df, label, value, value_title=value.replace("_", " ")))
    ui.table(df)

ui.page_footer()
