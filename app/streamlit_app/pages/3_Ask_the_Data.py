"""Ask the Data — controlled text-to-SQL over the marts (Ollama by default)."""

from __future__ import annotations

import streamlit as st
from streamlit_app.agent import build_sql
from streamlit_app.db import run_df, table_exists

from jmi_core.settings import get_settings
from jmi_enrichment.providers import get_provider

st.set_page_config(page_title="Ask the Data", page_icon="💬", layout="wide")
st.title("💬 Ask the Data")
st.caption("Natural-language questions → read-only SQL over the marts. Runs on your local LLM.")

if not table_exists("marts.FT_JOB_POSTING"):
    st.warning("Run the pipeline + `make dbt-build` first.")
    st.stop()

settings = get_settings()
st.caption(f"LLM provider: `{settings.llm_provider}` · model: `{settings.llm_model}`")

examples = [
    "How many visa-sponsoring postings are there per country?",
    "Top 10 technologies in roles that explicitly sponsor visas",
    "Companies hiring remote Data Engineers where English is sufficient",
]
question = st.text_input("Your question", value=examples[0])
st.caption("Examples: " + " · ".join(f"_{e}_" for e in examples))

if st.button("Ask", type="primary") and question.strip():
    with st.spinner("Generating SQL with the local model…"):
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

    st.success(f"{len(df)} rows")
    st.dataframe(df, use_container_width=True, hide_index=True)
    if df.shape[1] == 2 and df.select_dtypes("number").shape[1] == 1:
        st.bar_chart(df.set_index(df.columns[0]))
