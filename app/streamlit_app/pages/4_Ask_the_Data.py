"""Ask the Data — controlled text-to-SQL over the marts (SELECT-only guard)."""

from __future__ import annotations

import streamlit as st
from streamlit_app import limits, ui
from streamlit_app.agent import MAX_QUESTION_CHARS, build_sql
from streamlit_app.db import QueryRefused, require_marts, run_untrusted

from jmi_core.settings import get_settings
from jmi_enrichment.providers import get_provider, redact

ui.configure_page("Ask the Data")
ui.page_header(
    title="Ask the Data",
    subtitle="Ask a question in plain English. An LLM writes the SQL; you get to read it first.",
)
st.markdown(
    "Useful when the question you have isn't one of the filters — *\"which companies hire "
    'for dbt in Spain but not in Germany?"*. **The generated SQL is always shown**, so you '
    "can check it rather than trust it, and it is rejected unless it is a single read-only "
    "query against the five published tables."
)

require_marts(
    "marts.FT_JOB_POSTING",
    missing="Connected, but no marts yet — run the pipeline, then `make dbt-build`.",
)

settings = get_settings()
# Filled in at the end of the script, once this run's call has been counted.
budget_line = st.empty()

examples = [
    "Which technologies are most in demand in Spain?",
    "Compare open data roles per country",
    "Top 10 technologies in Sweden vs the Netherlands",
    "Companies hiring Data Engineers where English is sufficient",
]

if "ask_q" not in st.session_state:
    st.session_state.ask_q = examples[0]


def _pick(example: str) -> None:
    # A callback, so the question is in the box *and* asked in the same click.
    # Setting it inline meant a second click on "Ask" that nothing announced.
    st.session_state.ask_q = example
    st.session_state.ask_now = True


st.write("**Try one:**")
cols = st.columns(2)
for i, ex in enumerate(examples):
    cols[i % 2].button(ex, width="stretch", on_click=_pick, args=(ex,))

with st.form("ask", border=False):
    question = st.text_input("Your question", key="ask_q", max_chars=MAX_QUESTION_CHARS)
    go = st.form_submit_button("Ask", type="primary")
go = go or st.session_state.pop("ask_now", False)


def _answer(asked: str) -> dict:
    """One question, start to finish. Never raises; what failed is in the dict."""
    if not limits.spend_llm_call():
        return {"question": asked, "error": limits.budget_caption()}
    try:
        sql = build_sql(asked, get_provider(settings))
    except ValueError as exc:
        # The guard's own refusals: written to be read, and they quote the SQL.
        return {"question": asked, "error": f"That did not produce a query I can run. {exc}"}
    except Exception as exc:
        # The provider call. Its messages are scrubbed of credentials at the
        # source (providers.redact); the type alone is enough for a visitor.
        return {
            "question": asked,
            "error": "The LLM call failed — most often the free tier's daily quota. "
            f"Try again later. ({type(exc).__name__})",
        }
    try:
        return {"question": asked, "sql": sql, "df": run_untrusted(sql)}
    except QueryRefused as exc:
        return {"question": asked, "sql": sql, "error": str(exc)}
    except Exception as exc:
        # A database error on generated SQL is nearly always a column the model
        # invented; the first line names it and carries nothing sensitive.
        reason = redact(str(exc)).strip().splitlines()[0][:300]
        return {"question": asked, "sql": sql, "error": f"The query did not run: {reason}"}


if go and question.strip():
    with st.spinner("Writing the SQL and running it…"):
        st.session_state.ask_result = _answer(question.strip())

# Rendered from the session, not from inside `if go`: any rerun — sorting the
# table, opening the help — used to erase an answer that cost a rationed call.
result = st.session_state.get("ask_result")
if result:
    st.markdown(f"##### {ui.md_text(result['question'])}")
    if "sql" in result:
        st.code(result["sql"], language="sql")
    if "error" in result:
        st.error(result["error"])
    else:
        df = result["df"]
        if df.empty:
            st.info(
                "The query ran and matched nothing. Read the SQL above: a filter on an "
                "exact spelling (`'Data Engineer'`) is the usual reason."
            )
        else:
            st.caption(f"{len(df):,} row{'s' if len(df) != 1 else ''}")
            # Auto-chart a clean 2-column (label, measure) result.
            numeric = df.select_dtypes("number")
            if df.shape[1] == 2 and numeric.shape[1] == 1 and 1 <= len(df) <= 30:
                label = next(c for c in df.columns if c not in numeric.columns)
                value = numeric.columns[0]
                ui.altair_chart(ui.hbar(df, label, value, value_title=value.replace("_", " ")))
            ui.table(df)

budget_line.caption(
    f"One LLM call per question, on a free tier (`{settings.llm_provider}` / "
    f"`{settings.llm_model}`), so calls are rationed. {limits.budget_caption()}"
)

ui.page_footer()
