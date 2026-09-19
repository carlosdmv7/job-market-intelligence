"""Market Detail — one country at a time, including how well we can see it.

Market Trends compares the five markets against each other. This page goes the
other way: pick one and get everything about it, including the part most job
boards never admit — **how much of that market is actually legible**. The
answer differs enormously by country, and not for any reason about the country:
each market is fed by one source, and the sources publish wildly different
amounts of text. Adzuna (ES/DE/NL) truncates a posting to ~500 characters,
JobTech (SE) publishes ~4,000, so the same classifier extracts about one
technology from an Adzuna posting and about eight from a JobTech one.

That is why the stack lists here carry a warning against cross-market
comparison, and why "roles we can stack-match" is a headline metric rather than
a footnote: it is the number that decides whether My Fit is useful in a market.

This page also absorbs what used to be a standalone Netherlands visa page. The
IND recognised-sponsor cross-reference is a real, auditable signal, but it is a
property *of one market*, so it belongs inside that market's page rather than
in the navigation as if the whole app were about relocation to the Netherlands.
It renders only when the Netherlands is selected.
"""

from __future__ import annotations

import pandas as pd
import streamlit as st
from streamlit_app import ui
from streamlit_app.db import require_marts, run_df, staging_available

ui.configure_page("Market Detail")
ui.page_header(
    title="🌍 Market Detail",
    subtitle=(
        "One market at a time: what is open, what it asks for, who is hiring — "
        "and how much of it we can actually read."
    ),
)

require_marts(
    "marts.FT_JOB_POSTING",
    missing="Connected, but no marts yet — run the pipeline, then `make dbt-build`.",
)

# --- pick a market ----------------------------------------------------------
markets = run_df(
    """
    select coalesce(country_code, 'REMOTE') as code, count(*) as open_roles
    from marts.FT_JOB_POSTING
    where is_target_role and is_active
    group by 1 order by open_roles desc
    """
)
if markets.empty:
    st.info("No open data roles in the warehouse yet — run the pipeline.")
    ui.page_footer()
    st.stop()

codes = markets["code"].tolist()
labels = {c: ("🌍 Remote / global" if c == "REMOTE" else ui.market_label(c)) for c in codes}
picked = st.radio(
    "Market",
    codes,
    format_func=lambda c: (
        f"{labels[c]} · {int(markets.loc[markets['code'] == c, 'open_roles'].iloc[0]):,}"
    ),
    horizontal=True,
    label_visibility="collapsed",
)


def scope(alias: str = "") -> str:
    """The market filter, optionally qualified for a joined query.

    REMOTE is the bucket for postings with no country, so it is a null test
    rather than an equality test — and the country code is always bound as a
    parameter, never formatted into the SQL.
    """
    q = f"{alias}." if alias else ""
    match = f"{q}country_code is null" if picked == "REMOTE" else f"{q}country_code = ?"
    return f"{q}is_target_role and {q}is_active and {match}"


params: tuple = () if picked == "REMOTE" else (picked,)
SCOPE = scope()

st.markdown(f"### {labels[picked]}")

# --- the headline numbers ---------------------------------------------------
facts = run_df(
    f"""
    select
        count(*)                                                as open_roles,
        count(distinct company_name)                            as companies,
        count(*) filter (where detected_language = 'en')        as ads_in_english,
        count(*) filter (where len(technologies) > 0)           as with_stack,
        count(*) filter (where is_enriched)                     as llm_read
    from marts.FT_JOB_POSTING
    where {SCOPE}
    """,
    params,
).iloc[0]

open_roles = int(facts.open_roles)
k1, k2, k3, k4 = st.columns(4)
k1.metric("Open data roles", f"{open_roles:,}")
k2.metric("Companies hiring", f"{int(facts.companies):,}")
k3.metric(
    "Ads written in English",
    f"{int(facts.ads_in_english) / open_roles:.0%}" if open_roles else "—",
    help=(
        "Detected on ingest from the text itself, so it covers every posting. "
        "If you don't speak the local language this is the practical filter."
    ),
)
k4.metric(
    "Roles we can stack-match",
    f"{int(facts.with_stack) / open_roles:.0%}" if open_roles else "—",
    help=(
        "Share with at least one technology extracted — the roles My Fit can "
        "rank against your CV. Driven by how much text the source publishes, "
        "not by the market itself. See below."
    ),
)

st.divider()

# --- the honest bit: how legible is this market ------------------------------
st.markdown("#### How well we can see this market")

# staging.stg_job_postings is at *observation* grain — one row per sighting, so
# a posting seen daily for three weeks appears twenty-one times. Joining it
# directly multiplied the count (229 Spanish roles rendered as 5,160) and
# silently weighted the averages toward whatever has been on the board longest.
# One description per content_hash first, then join.
legibility = pd.DataFrame()
if not staging_available():
    st.info(
        "This section needs the posting text itself, which lives in `staging` and "
        "is not part of the committed demo sample — full descriptions are "
        "megabytes and a committed file here is capped at 512 KB. Connect a "
        "warehouse to see it.",
        icon="📦",
    )
else:
    legibility = run_df(
        f"""
        with described as (
            select content_hash, max(length(description_raw)) as chars
            from staging.stg_job_postings
            group by content_hash
        )
        select
            p.source,
            count(*)                                    as postings,
            round(avg(d.chars))                         as avg_chars,
            round(avg(len(p.technologies)), 2)          as avg_techs
        from marts.FT_JOB_POSTING p
        join described d on d.content_hash = p.content_hash
        where {scope("p")}
        group by 1 order by postings desc
        """,
        params,
    )

if not legibility.empty:
    ui.table(
        legibility,
        column_config={
            "source": st.column_config.TextColumn("Source"),
            "postings": st.column_config.NumberColumn("Postings"),
            "avg_chars": st.column_config.NumberColumn(
                "Avg. description length",
                help="Characters of job text the source actually publishes.",
            ),
            "avg_techs": st.column_config.NumberColumn(
                "Avg. technologies found",
                format="%.2f",
                help="What the classifier could extract from that text.",
            ),
        },
    )
    st.caption(
        "**The second column explains the fourth KPI, and neither is about the "
        "country.** Each market here is fed by a single board, and the boards "
        "publish very different amounts of text: Adzuna (ES · DE · NL) returns a "
        "~500-character teaser, JobTech (SE) returns the full ad at ~4,000. The "
        "same classifier reading both finds under one technology per Adzuna "
        "posting and around eight per JobTech one. Nothing is missing from the "
        "pipeline — the text was never there to read."
    )

st.divider()

# --- what this market asks for ----------------------------------------------
stack_col, seniority_col = st.columns([3, 2], gap="large")

with stack_col:
    st.markdown("#### What this market asks for")
    stacks = run_df(
        f"""
        select tech, count(*) as roles from (
            select unnest(technologies) as tech
            from marts.FT_JOB_POSTING where {SCOPE}
        ) group by 1 order by roles desc limit 12
        """,
        params,
    )
    if stacks.empty:
        st.info("No technologies extracted for this market yet.")
    else:
        ui.show(ui.hbar(stacks, "tech", "roles", color=ui.ACCENT, value_title="open roles"))
        st.caption(
            "⚠️ **Read this within the market, never across markets.** A stack "
            "looks rarer in Spain than in Sweden because Spanish ads are "
            "published truncated, not because Spanish employers want it less. "
            "The ranking inside one column is meaningful; the heights between "
            "two markets are not."
        )

with seniority_col:
    st.markdown("#### Seniority on offer")
    seniority = run_df(
        f"""
        select
            case when seniority is null or seniority = 'unknown'
                 then 'not stated' else seniority end  as level,
            count(*)                                   as roles
        from marts.FT_JOB_POSTING where {SCOPE}
        group by 1 order by roles desc
        """,
        params,
    )
    if not seniority.empty:
        seniority["share"] = seniority["roles"] / max(open_roles, 1)
        ui.table(
            seniority,
            column_config={
                "level": st.column_config.TextColumn("Level"),
                "roles": st.column_config.NumberColumn("Roles"),
                "share": st.column_config.ProgressColumn(
                    "Share", format="percent", min_value=0.0, max_value=1.0
                ),
            },
        )
        st.caption(
            "`not stated` is the LLM finding no seniority in the text — the same "
            "truncation that costs the stack also costs this."
        )

st.markdown("#### Who is hiring here")
companies = run_df(
    f"""
    select company_name, count(*) as open_roles
    from marts.FT_JOB_POSTING
    where {SCOPE} and company_name is not null
    group by 1 order by open_roles desc limit 12
    """,
    params,
)
if not companies.empty:
    ui.show(ui.hbar(companies, "company_name", "open_roles", value_title="open roles"))

# --- the Netherlands-only auditable signal ----------------------------------
# One market publishes a machine-readable register of who may legally sponsor a
# work visa, so one market gets an extra section. It used to be a page of its
# own in the top navigation, which made a five-country app read as a Dutch
# relocation tool — the signal is real, but it is a property of this market,
# not of the product.
if picked == "NL":
    st.divider()
    st.markdown("#### 🏛️ Who can legally sponsor a visa — the auditable signal")
    st.markdown(
        "The Netherlands is the only tracked market that publishes a "
        "machine-readable register of employers allowed to sponsor a "
        "highly-skilled-migrant visa. Every company here is matched against it, "
        "and a match carries the company's **KvK number** — so you can verify "
        "any flag on this page against a public registry rather than trusting "
        "this app. **Irrelevant with an EU passport**; it is kept because it is "
        "the clearest example in the project of a fact that should be looked up "
        "rather than inferred."
    )

    rates = run_df(
        """
        select
            case when country_code = 'NL' then 'NL local corpus (Adzuna)'
                 else 'Other / remote boards' end        as corpus,
            count(distinct company_name)                 as companies,
            count(distinct company_name)
                filter (where is_recognised_sponsor)     as sponsors
        from marts.FT_JOB_POSTING
        where company_name is not null
        group by 1 order by 1
        """
    )
    if not rates.empty:
        rates["sponsor_rate"] = rates["sponsors"] / rates["companies"]
        r1, r2 = st.columns(2)
        for col, (_, r) in zip((r1, r2), rates.iterrows(), strict=False):
            col.metric(
                f"Sponsor rate — {r['corpus']}",
                f"{r['sponsor_rate']:.0%}",
                help=(
                    f"{int(r['sponsors'])} of {int(r['companies'])} companies are on "
                    "the IND register. Whole corpus, not only data roles: it is a "
                    "property of the employers, not of the roles they advertise."
                ),
            )
        st.caption(
            "The gap is the point. A model reading job text would never produce it — "
            "and it holds for postings the LLM has never seen, because the register "
            "join needs no enrichment at all."
        )

    with st.expander("What are IND and KvK?"):
        st.markdown(
            """
- **IND** is the Dutch immigration service. It publishes the official list of
  employers allowed to sponsor a work visa for a non-EU hire.
- **KvK** is the Dutch chamber-of-commerce number — the local equivalent of a
  Spanish CIF/NIF. Showing it proves the match is the *actual registered
  company* and not a similar-looking name.
"""
        )

# --- the postings, and the evidence behind any one of them ------------------
st.divider()
st.markdown("#### Open postings in this market")

df = run_df(
    f"""
    select
        content_hash, title, company_name, country_code, seniority, salary_raw,
        source, source_url, detected_language, technologies, normalized_role,
        is_enriched, english_sufficient, working_languages,
        is_recognised_sponsor, sponsor_kvk, visa_status, visa_evidence,
        posted_at, last_seen_at
    from marts.FT_JOB_POSTING
    where {SCOPE}
    order by is_recognised_sponsor desc, last_seen_at desc nulls last
    limit 1000
    """,
    params,
)

grid = ui.add_salary_eur(df)
grid["market"] = grid["country_code"].map(ui.market_label)
columns = ["title", "company_name", "seniority", "technologies", "salary_eur", "posted_at"]
config = ui.posting_columns(
    seniority=st.column_config.TextColumn("Seniority"),
    technologies=st.column_config.ListColumn(
        "Stack", help="Technologies the LLM found. Empty = the ad was too short to name any."
    ),
)
if picked == "NL":
    columns.insert(2, "sponsor_kvk")
columns += ["source_url", "source"]

event = st.dataframe(
    grid[columns],
    width="stretch",
    hide_index=True,
    on_select="rerun",
    selection_mode="single-row",
    height=400,
    column_config=config,
)


def _items(value) -> list:
    """An array cell as a list; DuckDB returns pd.NA (not None) when NULL."""
    if value is None or (pd.api.types.is_scalar(value) and pd.isna(value)):
        return []
    return list(value)


rows = ui.selected_rows(event)
if not rows:
    st.caption("👆 Select a posting to see what is known about it and where that came from.")
    ui.page_footer()
    st.stop()

row = df.iloc[rows[0]]
st.divider()
st.markdown(f"#### {row['title']} — {row['company_name'] or 'unknown company'}")

d1, d2 = st.columns(2, gap="large")
with d1:
    st.markdown("##### 🧰 What the posting asks for")
    techs = _items(row["technologies"])
    if techs:
        st.markdown(" ".join(f"`{t}`" for t in techs))
    else:
        st.caption(
            "No technologies named in the text. On a truncated source that usually "
            "means the ad was cut before its requirements, not that it has none."
        )
    bits = [
        f"**Role:** {row['normalized_role']}" if pd.notna(row["normalized_role"]) else None,
        f"**Seniority:** {row['seniority']}" if pd.notna(row["seniority"]) else None,
    ]
    if any(bits):
        st.markdown(" · ".join(b for b in bits if b))
    st.caption(f"The ad is written in `{row['detected_language'] or 'unknown'}`.")
    if pd.notna(row["english_sufficient"]):
        if row["english_sufficient"]:
            st.success("**English is enough** for this job, per the posting text.")
        else:
            st.warning("**The local language is required** to do this job.")

with d2:
    if picked == "NL":
        st.markdown("##### 🏛️ Right-to-work signal")
        if row["is_recognised_sponsor"]:
            st.success("**Recognised sponsor** — on the IND register.")
            kvk = row["sponsor_kvk"]
            if kvk and not pd.isna(kvk):
                st.markdown(
                    f"KvK **{kvk}** — "
                    f"[verify on the public registry ↗]"
                    f"(https://www.kvk.nl/zoeken/?source=all&q={kvk})"
                )
            st.caption(
                "A normalized-name join against the IND seed, applied identically to "
                "both sides. No model, no confidence score, nothing to hallucinate."
            )
        else:
            st.info("**No register match** — this company is not on the IND list.")
            st.caption("A fact about the register, not about the company's intentions.")
        if row["is_enriched"] and pd.notna(row["visa_evidence"]) and row["visa_evidence"]:
            st.markdown(f"The model also quoted: “{row['visa_evidence']}”")
    else:
        st.markdown("##### 🗣️ Working language")
        langs = _items(row["working_languages"])
        if langs:
            st.markdown("Named in the ad: " + ", ".join(f"`{lang}`" for lang in langs))
        else:
            st.caption("The ad names no working language explicitly.")
        st.caption(
            "This market publishes no register of who may sponsor a work visa — "
            "only the Netherlands does, and that section appears when you select it."
        )

st.link_button("Open the original posting ↗", row["source_url"])

ui.page_footer()
