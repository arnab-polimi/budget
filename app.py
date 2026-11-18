import io
import json
import os
from datetime import datetime, date, timedelta
import pandas as pd
import plotly.express as px
import streamlit as st

import importlib
import bper_importer
import database
import ai_interrogator
import financial_advisor

importlib.reload(database)
importlib.reload(bper_importer)
importlib.reload(ai_interrogator)
importlib.reload(financial_advisor)

from database import (
    init_db,
    get_all_settings,
    set_setting,
    encode_secret,
    decode_secret,
    get_local_git_credential_token,
    get_categories_df,
    update_category_budget,
    add_transaction,
    update_transaction_verdict,
    bulk_update_merchant_verdict,
    bulk_update_transactions_by_ids,
    bulk_delete_transactions_by_ids,
    delete_transaction,
    get_transactions_df,
    add_to_wishlist,
    get_wishlist_df,
    update_wishlist_status,
    sync_db_to_github,
    pull_db_from_github,
)
from bper_importer import (
    parse_bper_file,
    scan_workspace_bper_pdfs,
    parse_multiple_bper_pdfs,
)
from ai_interrogator import compute_opportunity_cost, interrogate_transaction
from financial_advisor import compute_financial_intelligence

st.set_page_config(
    page_title="Ledger 2027",
    layout="wide",
    initial_sidebar_state="expanded",
)

init_db()

# Minimalist editorial styling: Inter + JetBrains Mono, hairline borders, zero visual clutter
st.markdown(
    """
    <style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600&family=JetBrains+Mono:wght@400;500&display=swap');

    html, body, [class*="css"] {
        font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif;
        letter-spacing: -0.011em;
    }

    code, pre, [data-testid="stMetricValue"] {
        font-family: 'JetBrains Mono', monospace !important;
    }

    .block-container {
        padding-top: 2.2rem;
        padding-bottom: 3rem;
        max-width: 1280px;
    }

    h1, h2, h3, h4 {
        font-weight: 500 !important;
        letter-spacing: -0.025em !important;
        color: #F4F4F6 !important;
    }

    /* Metric cards */
    [data-testid="stMetric"] {
        background-color: #111113;
        border: 1px solid #1F1F23;
        border-radius: 6px;
        padding: 16px 18px;
    }
    [data-testid="stMetricLabel"] {
        font-size: 0.76rem !important;
        text-transform: uppercase;
        letter-spacing: 0.06em;
        color: #8A8A93 !important;
    }
    [data-testid="stMetricValue"] {
        font-size: 1.5rem !important;
        font-weight: 500 !important;
        color: #F4F4F6 !important;
    }
    [data-testid="stMetricDelta"] {
        font-size: 0.78rem !important;
        font-family: 'JetBrains Mono', monospace !important;
    }

    /* Subtle cards */
    .spec-card {
        background-color: #111113;
        border: 1px solid #1F1F23;
        border-radius: 6px;
        padding: 18px 20px;
        margin-bottom: 14px;
    }
    .spec-label {
        font-size: 0.72rem;
        text-transform: uppercase;
        letter-spacing: 0.07em;
        color: #7D7D87;
        margin-bottom: 4px;
    }
    .spec-value {
        font-family: 'JetBrains Mono', monospace;
        font-size: 0.95rem;
        color: #EDEDEF;
    }
    .spec-grid {
        display: grid;
        grid-template-columns: repeat(2, 1fr);
        gap: 14px;
        margin-top: 10px;
    }

    /* Clean tabs */
    .stTabs [data-baseweb="tab-list"] {
        gap: 24px;
        border-bottom: 1px solid #1F1F23;
    }
    .stTabs [data-baseweb="tab"] {
        font-size: 0.85rem;
        font-weight: 400;
        color: #8A8A93;
        padding-bottom: 10px;
    }
    .stTabs [aria-selected="true"] {
        color: #F4F4F6 !important;
        font-weight: 500;
    }

    /* Sidebar refinement */
    [data-testid="stSidebar"] {
        background-color: #0D0D0F;
        border-right: 1px solid #1B1B1F;
    }

    hr {
        border-color: #1F1F23 !important;
        margin: 1.5rem 0 !important;
    }
    </style>
    """,
    unsafe_allow_html=True,
)


def _get_secret(key: str, default: str = "") -> str:
    try:
        if key in st.secrets:
            return str(st.secrets[key])
    except Exception:
        pass
    return os.environ.get(key, default)


def trigger_auto_github_sync(reason: str = "update") -> None:
    if st.session_state.get("auto_github_sync", True):
        token = st.session_state.get("gh_token") or _get_secret("GITHUB_TOKEN")
        repo = st.session_state.get("gh_repo") or _get_secret("GITHUB_REPO", "arnab-polimi/budget")
        branch = st.session_state.get("gh_branch") or _get_secret("GITHUB_BRANCH", "main")
        ok, msg = sync_db_to_github(
            github_token=token,
            github_repo=repo,
            github_branch=branch,
            commit_message=f"chore(db): sync after {reason}",
        )
        if ok:
            st.toast(f"Saved & synced ({reason})")
        else:
            st.toast(f"Saved locally ({msg})")


# Load settings
settings = get_all_settings()
hourly_wage = float(settings.get("hourly_wage", 14.0))
monthly_income_target = float(settings.get("monthly_income_target", 2200.0))
monthly_savings_goal = float(settings.get("monthly_savings_goal", 600.0))
suspect_threshold = float(settings.get("suspect_threshold_eur", 15.0))
eur_inr_rate = float(settings.get("eur_inr_rate", 90.0))
wise_invest_inr_per_300 = float(settings.get("wise_invest_inr_per_300", 12000.0))
monthly_pac_fondi_eur = float(settings.get("monthly_pac_fondi_eur", 100.0))
ai_provider = settings.get("ai_provider", "gemini")
ai_model = settings.get("ai_model", "gemini-2.5-flash")
strictness = settings.get("interrogator_strictness", "Direct & Analytical")

# Inbuilt & Persisted Credentials (auto-populates from DB / st.secrets / local Git credential store)
inbuilt_gh_token = (
    decode_secret(settings.get("github_token_b64", ""))
    or _get_secret("GITHUB_TOKEN")
    or get_local_git_credential_token()
)
if inbuilt_gh_token and not settings.get("github_token_b64"):
    set_setting("github_token_b64", encode_secret(inbuilt_gh_token))

inbuilt_ai_key = (
    decode_secret(settings.get("gemini_api_key_b64", ""))
    or _get_secret("GEMINI_API_KEY" if ai_provider == "gemini" else "OPENAI_API_KEY")
)
if inbuilt_ai_key and not settings.get("gemini_api_key_b64"):
    set_setting("gemini_api_key_b64", encode_secret(inbuilt_ai_key))

inbuilt_gh_repo = settings.get("github_repo", "") or _get_secret("GITHUB_REPO", "arnab-polimi/budget")
inbuilt_gh_branch = settings.get("github_branch", "") or _get_secret("GITHUB_BRANCH", "main")

categories_df = get_categories_df()
category_list = categories_df["name"].tolist()
tier_map = dict(zip(categories_df["name"], categories_df["tier"]))

all_tx_df = get_transactions_df()
pending_df = (
    all_tx_df[(all_tx_df["verdict"] == "Pending Review") & (all_tx_df["amount"] < 0)]
    if not all_tx_df.empty
    else pd.DataFrame()
)
pending_count = len(pending_df)

# --- SIDEBAR ---
with st.sidebar:
    st.markdown("### LEDGER 2027")
    st.caption("Personal Capital & Expense Audit")

    if pending_count > 0:
        st.markdown(
            f"<div class='spec-card' style='border-left: 2px solid #D97706; padding: 10px 14px;'>"
            f"<div class='spec-label'>Audit Queue</div>"
            f"<div class='spec-value'>{pending_count} pending review</div>"
            f"</div>",
            unsafe_allow_html=True,
        )
    else:
        st.markdown(
            "<div class='spec-card' style='border-left: 2px solid #10B981; padding: 10px 14px;'>"
            "<div class='spec-label'>Audit Queue</div>"
            "<div class='spec-value'>All transactions verified</div>"
            "</div>",
            unsafe_allow_html=True,
        )

    st.divider()
    st.markdown("##### Audit Engine")
    provider_choice = st.selectbox(
        "Provider",
        options=["gemini", "openai", "ollama"],
        index=["gemini", "openai", "ollama"].index(ai_provider) if ai_provider in ["gemini", "openai", "ollama"] else 0,
        help="Uses your saved API key if provided, otherwise runs the local rule-based auditor.",
    )
    api_key_input = st.text_input(
        "API Key (Saved Inbuilt)",
        value=st.session_state.get("user_api_key", inbuilt_ai_key),
        type="password",
        placeholder="Paste once to save inbuilt permanently",
    )
    if api_key_input != inbuilt_ai_key:
        set_setting("gemini_api_key_b64", encode_secret(api_key_input))
        trigger_auto_github_sync("save inbuilt AI key")
    st.session_state["user_api_key"] = api_key_input

    tone_options = ["Measured", "Direct & Analytical", "Strict"]
    strictness_choice = st.select_slider(
        "Audit Tone",
        options=tone_options,
        value=strictness if strictness in tone_options else "Direct & Analytical",
    )
    if provider_choice != ai_provider or strictness_choice != strictness:
        set_setting("ai_provider", provider_choice)
        set_setting("interrogator_strictness", strictness_choice)

    st.divider()
    st.markdown("##### GitHub Persistence")
    if inbuilt_gh_token:
        st.caption("✓ Inbuilt GitHub token active & persisted")
    with st.expander("Configure GitHub Sync", expanded=not bool(inbuilt_gh_token)):
        gh_repo = st.text_input(
            "Repository",
            value=st.session_state.get("gh_repo", inbuilt_gh_repo),
            placeholder="arnab-polimi/budget",
        )
        gh_token = st.text_input(
            "Access Token (Inbuilt)",
            value=st.session_state.get("gh_token", inbuilt_gh_token),
            type="password",
            placeholder="ghp_...",
        )
        gh_branch = st.text_input(
            "Branch",
            value=st.session_state.get("gh_branch", inbuilt_gh_branch),
        )
        if gh_token != inbuilt_gh_token or gh_repo != inbuilt_gh_repo or gh_branch != inbuilt_gh_branch:
            set_setting("github_token_b64", encode_secret(gh_token))
            set_setting("github_repo", gh_repo)
            set_setting("github_branch", gh_branch)
        st.session_state["gh_repo"] = gh_repo
        st.session_state["gh_token"] = gh_token
        st.session_state["gh_branch"] = gh_branch

    st.checkbox("Auto-commit on write", key="auto_github_sync", value=True)

    col_gh1, col_gh2 = st.columns(2)
    with col_gh1:
        if st.button("Push", width="stretch"):
            ok, msg = sync_db_to_github(gh_token, gh_repo, gh_branch)
            if ok:
                st.caption(msg)
            else:
                st.error(msg)
    with col_gh2:
        if st.button("Pull", width="stretch"):
            ok, msg = pull_db_from_github(gh_token, gh_repo, gh_branch)
            if ok:
                st.rerun()
            else:
                st.error(msg)


# --- NAVIGATION TABS ---
audit_tab_label = f"Audit ({pending_count})" if pending_count > 0 else "Audit"
tabs = st.tabs(
    [
        "Overview",
        "Advisory & Savings",
        "Log",
        audit_tab_label,
        "BPER Import",
        "Holding Vault",
        "Settings",
    ]
)

# ==============================================================================
# TAB 1: OVERVIEW
# ==============================================================================
with tabs[0]:
    f_col1, f_col2, f_col3, f_col4 = st.columns([1.0, 1.0, 0.9, 1.5])
    today = date.today()
    first_of_month = today.replace(day=1)

    with f_col1:
        timeframe = st.selectbox(
            "Period",
            options=["Current Month", "Last 30 Days", "Last 90 Days", "Year to Date", "2026 Only", "2025 Only", "All Time"],
            index=6,
        )
    if timeframe == "Current Month":
        start_d = first_of_month.strftime("%Y-%m-%d")
        end_d = None
    elif timeframe == "Last 30 Days":
        start_d = (today - timedelta(days=30)).strftime("%Y-%m-%d")
        end_d = None
    elif timeframe == "Last 90 Days":
        start_d = (today - timedelta(days=90)).strftime("%Y-%m-%d")
        end_d = None
    elif timeframe == "Year to Date":
        start_d = today.replace(month=1, day=1).strftime("%Y-%m-%d")
        end_d = None
    elif timeframe == "2026 Only":
        start_d = "2026-01-01"
        end_d = "2026-12-31"
    elif timeframe == "2025 Only":
        start_d = "2025-01-01"
        end_d = "2025-12-31"
    else:
        start_d = None
        end_d = None

    with f_col2:
        verdict_filter = st.selectbox(
            "Classification",
            options=["All", "Pending Review", "Guilty / Bad Purchase", "Justified", "Essential Pass", "Income"],
            index=0,
        )
    with f_col3:
        recurrence_filter = st.selectbox(
            "Frequency",
            options=["All", "Recurring", "One-Time"],
            index=0,
        )
    with f_col4:
        search_q = st.text_input("Filter ledger", placeholder="Merchant, category, or note...")

    df = get_transactions_df(start_date=start_d, end_date=end_d, verdict_filter=verdict_filter, recurrence_filter=recurrence_filter)
    if search_q and not df.empty:
        mask = (
            df["description"].str.contains(search_q, case=False, na=False)
            | df["merchant"].str.contains(search_q, case=False, na=False)
            | df["category"].str.contains(search_q, case=False, na=False)
            | df["ai_roast"].str.contains(search_q, case=False, na=False)
        )
        df = df[mask]

    if all_tx_df.empty:
        st.markdown(
            "<div class='spec-card'>"
            "<div class='spec-label'>No Transactions Recorded</div>"
            "<div style='color:#9E9EA8; font-size:0.9rem; margin-top:4px;'>"
            "Import a BPER statement under <b>BPER Import</b> or record a transaction under <b>Log</b>."
            "</div></div>",
            unsafe_allow_html=True,
        )
    else:
        expenses_df = df[df["amount"] < 0].copy() if not df.empty else pd.DataFrame()
        income_df = df[df["amount"] > 0].copy() if not df.empty else pd.DataFrame()

        total_spent = abs(expenses_df["amount"].sum()) if not expenses_df.empty else 0.0
        total_income = income_df["amount"].sum() if not income_df.empty else 0.0
        net_saved = total_income - total_spent

        unjustified_spent = (
            abs(expenses_df[expenses_df["verdict"] == "Guilty / Bad Purchase"]["amount"].sum())
            if not expenses_df.empty
            else 0.0
        )
        pending_spent = (
            abs(expenses_df[expenses_df["verdict"] == "Pending Review"]["amount"].sum())
            if not expenses_df.empty
            else 0.0
        )
        hours_burned = total_spent / max(hourly_wage, 1.0)
        unjustified_10y = unjustified_spent * ((1.08) ** 10)

        w_df = get_wishlist_df()
        skipped_saved = (
            w_df[w_df["status"] == "Skipped & Saved"]["price"].sum() if not w_df.empty else 0.0
        )

        m1, m2, m3, m4, m5 = st.columns(5)
        m1.metric("Outflow", f"€{total_spent:,.2f}", f"{hours_burned:.1f}h labor", delta_color="off")
        m2.metric("Inflow", f"€{total_income:,.2f}", f"Net €{net_saved:+,.2f}", delta_color="off")
        m3.metric(
            "Unjustified",
            f"€{unjustified_spent:,.2f}",
            f"€{unjustified_10y:,.0f} @ 10Y",
            delta_color="inverse" if unjustified_spent > 0 else "off",
        )
        m4.metric(
            "Pending Audit",
            f"€{pending_spent:,.2f}",
            f"{len(expenses_df[expenses_df['verdict'] == 'Pending Review']) if not expenses_df.empty else 0} items",
            delta_color="off",
        )
        m5.metric("Capital Preserved", f"€{skipped_saved:,.2f}", "Holding vault", delta_color="off")

        st.write("")

        if not expenses_df.empty:
            c1, c2 = st.columns(2)
            color_map = {
                "Essential Pass": "#3F3F46",
                "Justified": "#10B981",
                "Pending Review": "#D97706",
                "Guilty / Bad Purchase": "#EF4444",
            }
            with c1:
                st.markdown("##### Allocation by Category")
                expenses_df["abs_amount"] = expenses_df["amount"].abs()
                fig_cat = px.bar(
                    expenses_df.groupby(["category", "verdict"], as_index=False)["abs_amount"].sum(),
                    x="abs_amount",
                    y="category",
                    color="verdict",
                    orientation="h",
                    color_discrete_map=color_map,
                    labels={"abs_amount": "EUR", "category": "", "verdict": ""},
                )
                fig_cat.update_layout(
                    paper_bgcolor="rgba(0,0,0,0)",
                    plot_bgcolor="rgba(0,0,0,0)",
                    font=dict(family="Inter, sans-serif", size=11, color="#9E9EA8"),
                    margin=dict(l=0, r=10, t=10, b=0),
                    height=310,
                    xaxis=dict(showgrid=True, gridcolor="#18181B", zeroline=False),
                    yaxis=dict(showgrid=False),
                    legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
                )
                st.plotly_chart(fig_cat, width="stretch")

            with c2:
                st.markdown("##### Daily Outflow")
                daily_df = (
                    expenses_df.groupby(["tx_date", "verdict"], as_index=False)["abs_amount"]
                    .sum()
                    .sort_values("tx_date")
                )
                fig_daily = px.bar(
                    daily_df,
                    x="tx_date",
                    y="abs_amount",
                    color="verdict",
                    color_discrete_map=color_map,
                    labels={"tx_date": "", "abs_amount": "EUR", "verdict": ""},
                )
                fig_daily.update_layout(
                    paper_bgcolor="rgba(0,0,0,0)",
                    plot_bgcolor="rgba(0,0,0,0)",
                    font=dict(family="Inter, sans-serif", size=11, color="#9E9EA8"),
                    margin=dict(l=0, r=10, t=10, b=0),
                    height=310,
                    xaxis=dict(showgrid=False),
                    yaxis=dict(showgrid=True, gridcolor="#18181B", zeroline=False),
                    legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
                )
                st.plotly_chart(fig_daily, width="stretch")

            st.markdown("##### Monthly Budget Utilization")
            cat_spend = expenses_df.groupby("category")["abs_amount"].sum().to_dict()
            env_cols = st.columns(3)
            expense_cats = categories_df[~categories_df["tier"].isin(["Income", "Savings"])].reset_index(drop=True)
            for idx, crow in expense_cats.iterrows():
                cname = crow["name"]
                limit = float(crow["monthly_limit"])
                spent = float(cat_spend.get(cname, 0.0))
                pct = min(spent / limit, 1.0) if limit > 0 else 0.0
                with env_cols[idx % 3]:
                    st.progress(
                        pct,
                        text=f"{cname} — €{spent:.0f} / €{limit:.0f}",
                    )

        st.divider()
        st.markdown("##### Ledger")
        display_df = df[
            ["id", "tx_date", "merchant", "category", "recurrence", "amount", "verdict", "ai_roast", "source"]
        ].copy()
        display_df.columns = [
            "ID",
            "Date",
            "Merchant",
            "Category",
            "Frequency",
            "Amount",
            "Status",
            "Audit Note",
            "Source",
        ]
        st.dataframe(
            display_df,
            width="stretch",
            hide_index=True,
            column_config={
                "Amount": st.column_config.NumberColumn(format="€ %.2f"),
            },
        )


# ==============================================================================
# TAB 2: ADVISORY & SAVINGS PLAN
# ==============================================================================
with tabs[1]:
    with st.expander("Interactive Savings Simulator & Audit Filter", expanded=False):
        st.caption(
            "Adjust your target reduction percentage for each channel, or toggle whether transactions you already cleared as 'Justified' are excluded from savings leaks."
        )
        include_justified_toggle = st.checkbox(
            "Include 'Justified' transactions in leak calculations (uncheck so auditing transactions as Justified removes them from leaks)",
            value=False,
        )
        sl1, sl2, sl3, sl4 = st.columns(4)
        with sl1:
            cut_bnpl = st.slider("PayPal 3-Rate Cut (%)", 0, 100, 75, 5) / 100.0
            cut_revolut = st.slider("Revolut Net Cut (%)", 0, 100, 50, 5) / 100.0
        with sl2:
            cut_retail = st.slider("Retail / Apparel Cut (%)", 0, 100, 50, 5) / 100.0
            cut_amazon = st.slider("Amazon Cut (%)", 0, 100, 60, 5) / 100.0
        with sl3:
            cut_delivery = st.slider("Glovo / Takeout Cut (%)", 0, 100, 80, 5) / 100.0
            cut_dining = st.slider("Dining / Events Cut (%)", 0, 100, 40, 5) / 100.0
        with sl4:
            cut_ppsdd = st.slider("PayPal SDD Cut (%)", 0, 100, 60, 5) / 100.0
            cut_fees = st.slider("BPER SDD Fees Cut (%)", 0, 100, 100, 10) / 100.0

    custom_ratios = {
        "bnpl": cut_bnpl,
        "revolut": cut_revolut,
        "retail": cut_retail,
        "amazon": cut_amazon,
        "delivery": cut_delivery,
        "dining": cut_dining,
        "paypal_sdd": cut_ppsdd,
        "bper_fees": cut_fees,
    }

    intel = compute_financial_intelligence(
        all_tx_df,
        hourly_wage=hourly_wage,
        custom_cut_ratios=custom_ratios,
        include_justified_in_leaks=include_justified_toggle,
        eur_inr_rate=eur_inr_rate,
        wise_invest_inr_per_300=wise_invest_inr_per_300,
        monthly_pac_fondi_eur=monthly_pac_fondi_eur,
    )
    if intel.get("empty"):
        st.caption("No transaction data available for advisory analysis.")
    else:
        astats = intel["audit_stats"]
        # Top Scorecard Row
        sc1, sc2, sc3, sc4, sc5 = st.columns(5)
        sc1.metric(
            "Financial Wisdom Score",
            f"{intel['wisdom_score']} / 100",
            f"{intel['savings_rate_pct']:.1f}% effective savings rate",
            delta_color="off",
        )
        sc2.metric(
            "Active Investments",
            f"€{intel['total_invested_capital_eur']:,.2f}",
            f"€{intel['monthly_invested_avg_eur']:,.0f}/mo (Fondi PAC + Wise 12k INR)",
            delta_color="off",
        )
        sc3.metric(
            "Recoverable Leaks (Period)",
            f"€{intel['total_saveable_period']:,.2f}",
            f"€{intel['total_saveable_annualized']:,.0f} / year pace",
            delta_color="off",
        )
        sc4.metric(
            "Recoverable (Per Month)",
            f"€{intel['total_saveable_monthly']:,.2f}/mo",
            f"€{intel['recurring_saveable_monthly']:,.0f}/mo recurring · €{intel['onetime_saveable_monthly']:,.0f}/mo 1-time",
            delta_color="off",
        )
        sc5.metric(
            "Recurrence-Adjusted Forecast",
            f"€{intel['forecast_monthly_savings']:,.0f} / mo",
            f"€{intel['forecast_annual_savings']:,.0f}/yr projected on €{intel['base_monthly_income']:,.0f} salary",
            delta_color="off",
        )

        st.write("")
        diag_col, plan_col = st.columns([1.15, 1.0], gap="large")

        with diag_col:
            st.markdown("##### Executive Diagnosis — Reactive to Your Audit, Investments & Frequency Tags")
            sb = intel["score_breakdown"]
            st.markdown(
                f"""
                <div class="spec-card">
                    <div class="spec-label">Assessment · {intel['rating_label']}</div>
                    <div style="color:#D4D4D8; font-size:0.9rem; line-height:1.6; margin-top:8px;">
                        <b>1. Stock PAC & Wise INR Investments Credited ({sb['Retention & Audit Progress']}):</b> You have actively invested <b>€{intel['total_invested_capital_eur']:,.2f}</b> (<b>€{intel['monthly_invested_avg_eur']:,.0f}/mo</b>) across <b>SOTTOSCRIZIONI FONDI E SICAV</b> (€{intel['fondi_total_accredited_eur']:,.0f} stock PAC @ €{monthly_pac_fondi_eur:.0f}/mo) and <b>{intel['wise_gt300_cnt']} Wise transfers &gt;€300</b> ({intel['wise_invested_total_inr']:,.0f} INR ≈ <b>€{intel['wise_invested_total_eur']:,.2f}</b> @ {wise_invest_inr_per_300:,.0f} INR / tx). Including these investments, your true wealth accumulation is <b>€{intel['true_wealth_accumulated_eur']:+,.2f}</b> (<b>{intel['savings_rate_pct']:.1f}%</b> effective savings rate).<br/>
                        <b>2. Recurring vs. One-Time Split ({sb['Essential Overhead Control']}):</b> Outflow splits into <b>€{intel['recurring_monthly_burn']:,.0f}/mo Recurring</b> (€{intel['committed_recurring_monthly']:,.0f}/mo non-investment living baseline + €{intel['suspect_recurring_monthly']:,.0f}/mo unverified/BNPL recurring) and <b>€{intel['onetime_monthly_avg']:,.0f}/mo One-Time</b>.<br/>
                        <b>3. Forward Savings Forecast ({sb['Cashflow Consistency']}):</b> Combining your existing <b>€{intel['monthly_invested_avg_eur']:,.0f}/mo</b> automated investments with trimming recurring leaks (<b>+€{intel['recurring_saveable_monthly']:,.0f}/mo</b>) and capping one-time purchases at <b>€{intel['planned_onetime_allowance']:,.0f}/mo</b> forecasts <b>€{intel['forecast_monthly_savings']:,.0f}/mo</b> (<b>€{intel['forecast_annual_savings']:,.0f}/year</b>) in total wealth accumulation.
                    </div>
                </div>
                """,
                unsafe_allow_html=True,
            )

        with plan_col:
            st.markdown("##### Monthly Savings Prescription & Investment Breakdown")
            st.markdown(
                f"""
                <div class="spec-card">
                    <div class="spec-label">Forward Monthly Forecast (Base Salary: €{intel['base_monthly_income']:,.0f}/mo)</div>
                    <div class="spec-grid">
                        <div>
                            <div class="spec-label">1. Committed Living Baseline</div>
                            <div class="spec-value">€{intel['committed_recurring_monthly']:,.0f} / mo</div>
                            <div style="font-size:0.76rem; color:#7D7D87;">Rent (€600), Utilities, Mensa, Groceries, Remittance</div>
                        </div>
                        <div>
                            <div class="spec-label">2. Forecasted Total Savings</div>
                            <div class="spec-value" style="color:#10B981;">€{intel['forecast_monthly_savings']:,.0f} / mo</div>
                            <div style="font-size:0.76rem; color:#7D7D87;">€{intel['forecast_annual_savings']:,.0f}/yr (Investments + Recovered Leaks)</div>
                        </div>
                        <div>
                            <div class="spec-label">3. Stock PAC (Fondi e Sicav)</div>
                            <div class="spec-value" style="color:#10B981;">€{monthly_pac_fondi_eur:,.0f} / mo</div>
                            <div style="font-size:0.76rem; color:#7D7D87;">€{intel['fondi_total_accredited_eur']:,.0f} accumulated (Etica Azionario & Trans.Climat)</div>
                        </div>
                        <div>
                            <div class="spec-label">4. Wise &gt;€300 Investment (12k INR)</div>
                            <div class="spec-value" style="color:#10B981;">€{intel['wise_invested_total_eur']:,.0f} invested</div>
                            <div style="font-size:0.76rem; color:#7D7D87;">{intel['wise_gt300_cnt']} transfers &gt;€300 ({intel['wise_invested_total_inr']:,.0f} INR) out of €{intel['wise_total']:,.0f} Wise</div>
                        </div>
                    </div>
                </div>
                """,
                unsafe_allow_html=True,
            )

        st.markdown("##### Fast Bulk Merchant Audit (Instant Recalculation)")
        st.caption("Classify all transactions for a merchant at once — including whether it is a **One-Time** or **Recurring** expense — and watch the Savings Forecast update immediately.")
        bm_col1, bm_col2, bm_col3, bm_col4, bm_col5 = st.columns([1.4, 0.95, 0.9, 1.1, 0.75])
        expense_merchants = (
            all_tx_df[all_tx_df["amount"] < 0]
            .groupby("merchant")["amount"]
            .agg(cnt="count", total=lambda s: abs(s.sum()))
            .reset_index()
            .sort_values("total", ascending=False)
        )
        merchant_options = {
            f"{r['merchant']} ({r['cnt']} tx · €{r['total']:,.2f})": r["merchant"]
            for _, r in expense_merchants.iterrows()
        }
        with bm_col1:
            sel_m_label = st.selectbox("Merchant", options=list(merchant_options.keys()), label_visibility="collapsed")
            sel_m_name = merchant_options[sel_m_label]
        with bm_col2:
            sel_m_verdict = st.selectbox(
                "New Verdict",
                options=["Justified", "Guilty / Bad Purchase", "Essential Pass", "Pending Review"],
                label_visibility="collapsed",
            )
        with bm_col3:
            sel_m_rec = st.selectbox(
                "Frequency Override",
                options=["(Keep frequency)", "Recurring", "One-Time"],
                label_visibility="collapsed",
            )
        with bm_col4:
            sel_m_cat = st.selectbox(
                "Optional Category Override",
                options=["(Keep current category)"] + category_list,
                label_visibility="collapsed",
            )
        with bm_col5:
            if st.button("Apply to All", width="stretch"):
                cat_override = None if sel_m_cat == "(Keep current category)" else sel_m_cat
                rec_override = None if sel_m_rec == "(Keep frequency)" else sel_m_rec
                updated_n = bulk_update_merchant_verdict(
                    sel_m_name,
                    sel_m_verdict,
                    category=cat_override,
                    recurrence=rec_override,
                )
                trigger_auto_github_sync(f"bulk audit {sel_m_name}")
                st.toast(f"Updated {updated_n} transactions for {sel_m_name} to {sel_m_verdict}.")
                st.rerun()

        st.write("")
        st.markdown("##### Exact Places & Amounts You Could Have Saved (Live Audit & Recurrence-Adjusted)")
        display_leaks = intel["leaks_df"].drop(columns=["key", "rec_save_mo", "one_save_mo"], errors="ignore")
        st.dataframe(
            display_leaks,
            width="stretch",
            hide_index=True,
            column_config={
                "Total Spent (€)": st.column_config.NumberColumn("Total Spent", format="€ %.2f"),
                "Recurring (€)": st.column_config.NumberColumn("Recurring", format="€ %.2f"),
                "One-Time (€)": st.column_config.NumberColumn("One-Time", format="€ %.2f"),
                "Cleared / Justified (€)": st.column_config.NumberColumn("Cleared (Justified)", format="€ %.2f"),
                "Unjustified / Pending (€)": st.column_config.NumberColumn("Unjustified / Pending", format="€ %.2f"),
                "Target Cut (%)": st.column_config.NumberColumn("Cut %", format="%d%%"),
                "Saveable This Period (€)": st.column_config.NumberColumn("Saveable (Period)", format="€ %.2f"),
                "Saveable Per Month (€/mo)": st.column_config.NumberColumn("Saveable / Month", format="€ %.2f/mo"),
                "Labor Equivalent (h)": st.column_config.NumberColumn("Hours of Work", format="%.1f h"),
                "10Y Compounded (€)": st.column_config.NumberColumn("10Y S&P 500 Value", format="€ %.2f"),
            },
        )

        st.write("")
        st.markdown("##### Month-by-Month Cashflow, Investments & Recurring vs. One-Time Breakdown")
        st.dataframe(
            intel["monthly_summary_df"],
            width="stretch",
            hide_index=True,
            column_config={
                "Inflow (€)": st.column_config.NumberColumn(format="€ %.2f"),
                "Invested (Fondi + Wise 12k INR) (€)": st.column_config.NumberColumn("Invested (PAC + Wise)", format="€ %.2f"),
                "Recurring Outflow (€)": st.column_config.NumberColumn(format="€ %.2f"),
                "One-Time Outflow (€)": st.column_config.NumberColumn(format="€ %.2f"),
                "Essential (€)": st.column_config.NumberColumn(format="€ %.2f"),
                "Discretionary & Retail (€)": st.column_config.NumberColumn(format="€ %.2f"),
                "Transfers & P2P (€)": st.column_config.NumberColumn(format="€ %.2f"),
                "Total Outflow (€)": st.column_config.NumberColumn(format="€ %.2f"),
                "Net Cashflow (€)": st.column_config.NumberColumn(format="€ %+.2f"),
                "Net Wealth Retained + Invested (€)": st.column_config.NumberColumn("Net Wealth (+Invested)", format="€ %+.2f"),
                "Effective Savings Rate (%)": st.column_config.NumberColumn("Effective Save %", format="%.1f%%"),
            },
        )


# ==============================================================================
# TAB 3: LOG TRANSACTION
# ==============================================================================
with tabs[2]:
    q_col1, q_col2 = st.columns([1.15, 1.0], gap="large")

    with q_col1:
        st.markdown("##### Record Transaction")
        with st.form("quick_log_form", clear_on_submit=True):
            tx_kind = st.radio("Type", ["Expense", "Income"], horizontal=True, label_visibility="collapsed")
            c_amt, c_date = st.columns(2)
            with c_amt:
                amt_val = st.number_input("Amount (EUR)", min_value=0.01, max_value=100000.0, value=12.50, step=0.50, format="%.2f")
            with c_date:
                tx_d = st.date_input("Date", value=date.today())

            merchant_in = st.text_input("Merchant / Counterparty", placeholder="e.g. Esselunga, Glovo, Enel...")
            c_cat, c_rec = st.columns([1.4, 1.0])
            with c_cat:
                cat_in = st.selectbox("Category", options=category_list, index=4)
            with c_rec:
                rec_in = st.selectbox("Expense Frequency", options=["One-Time", "Recurring"], index=0)
            excuse_in = st.text_area(
                "Rationale (Optional)",
                placeholder="State the purpose of this expense (and whether one-time or recurring), or leave blank for review.",
                height=72,
            )

            submitted = st.form_submit_button("Record Entry", width="stretch")

        if submitted:
            if not merchant_in.strip():
                st.warning("Merchant name is required.")
            else:
                is_income = tx_kind == "Income"
                signed_amt = float(amt_val) if is_income else -float(amt_val)
                cat_tier = tier_map.get(cat_in, "Discretionary")

                if is_income:
                    verdict = "Income"
                    regret = 0
                    roast = "Inflow recorded."
                    history = []
                elif cat_tier == "Essential" and abs(signed_amt) <= suspect_threshold * 4:
                    verdict = "Essential Pass"
                    regret = 5
                    roast = f"Essential operating expense ({rec_in})."
                    history = []
                else:
                    init_conv = []
                    if excuse_in.strip():
                        init_conv.append({"role": "user", "content": excuse_in.strip()})

                    ai_reply, meta = interrogate_transaction(
                        merchant=merchant_in.strip(),
                        description=merchant_in.strip(),
                        amount=signed_amt,
                        category=cat_in,
                        tx_date=tx_d.strftime("%Y-%m-%d"),
                        conversation=init_conv,
                        provider=provider_choice,
                        model=ai_model,
                        api_key=st.session_state.get("user_api_key", ""),
                        strictness=strictness_choice,
                        hourly_wage=hourly_wage,
                        monthly_savings_goal=monthly_savings_goal,
                        recurrence=rec_in,
                    )
                    init_conv.append({"role": "assistant", "content": ai_reply})
                    verdict = str(meta.get("verdict_recommendation", "Pending Review"))
                    rec_in = str(meta.get("recurrence_recommendation", rec_in))
                    regret = int(meta.get("regret_score", 70))
                    roast = str(meta.get("one_line_roast", ai_reply[:110]))
                    history = init_conv

                ok, new_id = add_transaction(
                    tx_date=tx_d.strftime("%Y-%m-%d"),
                    description=merchant_in.strip(),
                    merchant=merchant_in.strip(),
                    amount=signed_amt,
                    category=cat_in,
                    source="Manual",
                    verdict=verdict,
                    regret_score=regret,
                    user_excuse=excuse_in.strip(),
                    ai_roast=roast,
                    interrogation_history=history,
                    recurrence=rec_in,
                )
                if ok:
                    st.session_state["last_logged_tx_id"] = new_id
                    trigger_auto_github_sync("manual entry")
                    st.rerun()

    with q_col2:
        st.markdown("##### Opportunity Cost Estimator")
        preview_amt = st.number_input("Evaluate Amount (EUR)", min_value=1.0, max_value=10000.0, value=35.0, step=5.0, format="%.2f")
        opp_preview = compute_opportunity_cost(preview_amt, hourly_wage=hourly_wage)
        st.markdown(
            f"""
            <div class="spec-card">
                <div class="spec-label">Capital & Labor Equivalence — €{preview_amt:.2f}</div>
                <div class="spec-grid">
                    <div>
                        <div class="spec-label">Labor Required</div>
                        <div class="spec-value">{opp_preview['hours_worked']} hours</div>
                    </div>
                    <div>
                        <div class="spec-label">10Y Value (8% p.a.)</div>
                        <div class="spec-value">€{opp_preview['fv_10y']:,.2f}</div>
                    </div>
                    <div>
                        <div class="spec-label">20Y Value (8% p.a.)</div>
                        <div class="spec-value">€{opp_preview['fv_20y']:,.2f}</div>
                    </div>
                    <div>
                        <div class="spec-label">If Weekly (10Y)</div>
                        <div class="spec-value">€{opp_preview['if_weekly_10y']:,.0f}</div>
                    </div>
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )

        last_id = st.session_state.get("last_logged_tx_id")
        if last_id and not all_tx_df.empty:
            match_rows = all_tx_df[all_tx_df["id"] == last_id]
            if not match_rows.empty:
                r = match_rows.iloc[0]
                st.markdown("##### Latest Audit Note")
                st.markdown(
                    f"<div class='spec-card'>"
                    f"<div class='spec-label'>{r['merchant']} · €{abs(r['amount']):.2f} · {r['verdict']}</div>"
                    f"<div style='color:#D4D4D8; font-size:0.9rem; margin-top:6px;'>{r['ai_roast']}</div>"
                    f"</div>",
                    unsafe_allow_html=True,
                )


# ==============================================================================
# TAB 4: AUDIT ROOM
# ==============================================================================
with tabs[3]:
    q_filter_col1, q_filter_col2, q_filter_col3 = st.columns([1.2, 1.0, 1.2])
    with q_filter_col1:
        audit_queue_mode = st.radio(
            "Queue View",
            options=["Pending Review Only", "Unjustified (Reviewed)", "Justified (Cleared)"],
            horizontal=True,
            label_visibility="collapsed",
        )
    with q_filter_col2:
        audit_selection_mode = st.radio(
            "Selection Mode",
            options=["Multi-Select Batch Table", "Single Live Audit"],
            horizontal=True,
            label_visibility="collapsed",
        )
    with q_filter_col3:
        audit_search = st.text_input("Filter queue by merchant or date...", placeholder="e.g. PayPal, Glovo, 2026-10...", label_visibility="collapsed")

    if audit_queue_mode == "Pending Review Only":
        target_verdicts = ["Pending Review"]
    elif audit_queue_mode == "Unjustified (Reviewed)":
        target_verdicts = ["Guilty / Bad Purchase"]
    else:
        target_verdicts = ["Justified"]

    suspect_choices_df = (
        all_tx_df[(all_tx_df["amount"] < 0) & (all_tx_df["verdict"].isin(target_verdicts))].copy()
        if not all_tx_df.empty
        else pd.DataFrame()
    )
    if audit_search and not suspect_choices_df.empty:
        s_mask = (
            suspect_choices_df["merchant"].str.contains(audit_search, case=False, na=False)
            | suspect_choices_df["description"].str.contains(audit_search, case=False, na=False)
            | suspect_choices_df["category"].str.contains(audit_search, case=False, na=False)
            | suspect_choices_df["tx_date"].str.contains(audit_search, case=False, na=False)
        )
        suspect_choices_df = suspect_choices_df[s_mask]

    if suspect_choices_df.empty:
        st.markdown(
            f"<div class='spec-card'>"
            f"<div class='spec-label'>{audit_queue_mode} — Empty</div>"
            f"<div style='color:#9E9EA8; font-size:0.9rem; margin-top:4px;'>"
            f"No transactions in this view."
            f"</div></div>",
            unsafe_allow_html=True,
        )
    elif audit_selection_mode == "Multi-Select Batch Table":
        st.markdown(f"##### Select Multiple Transactions to Audit Together ({len(suspect_choices_df)} in view)")

        if "batch_ed_ver" not in st.session_state:
            st.session_state["batch_ed_ver"] = 0

        sel_ctrl1, sel_ctrl2, sel_ctrl3 = st.columns([0.6, 0.6, 2.8])
        with sel_ctrl1:
            if st.button("Select All in View", width="stretch"):
                st.session_state["batch_select_all"] = True
                st.session_state["batch_ed_ver"] += 1
                st.rerun()
        with sel_ctrl2:
            if st.button("Clear Selection", width="stretch"):
                st.session_state["batch_select_all"] = False
                st.session_state["batch_ed_ver"] += 1
                st.rerun()

        default_check = bool(st.session_state.get("batch_select_all", False))
        batch_df = suspect_choices_df[["id", "tx_date", "merchant", "category", "recurrence", "amount", "verdict", "description"]].copy()
        batch_df.insert(0, "Select", default_check)

        edited_batch = st.data_editor(
            batch_df,
            width="stretch",
            hide_index=True,
            height=380,
            disabled=["id", "tx_date", "merchant", "amount", "verdict", "description"],
            column_config={
                "Select": st.column_config.CheckboxColumn("Select", default=False),
                "id": st.column_config.NumberColumn("ID", width="small"),
                "tx_date": "Date",
                "merchant": "Merchant",
                "category": st.column_config.SelectboxColumn("Category", options=category_list),
                "recurrence": st.column_config.SelectboxColumn("Frequency", options=["One-Time", "Recurring"]),
                "amount": st.column_config.NumberColumn("Amount", format="€ %.2f"),
                "verdict": "Current Status",
                "description": "Raw Bank Description",
            },
            key=f"multi_audit_editor_{st.session_state['batch_ed_ver']}_{audit_queue_mode}",
        )

        selected_rows = edited_batch[edited_batch["Select"] == True]
        selected_ids = selected_rows["id"].astype(int).tolist()
        selected_total = abs(float(selected_rows["amount"].sum())) if not selected_rows.empty else 0.0

        st.markdown(
            f"<div class='spec-card' style='padding:12px 16px;'>"
            f"<div class='spec-label'>Batch Selection</div>"
            f"<div class='spec-value'>{len(selected_ids)} transaction(s) selected  ·  Total: €{selected_total:,.2f}</div>"
            f"</div>",
            unsafe_allow_html=True,
        )

        act_col1, act_col2, act_col3 = st.columns([1.1, 0.9, 1.5])
        with act_col1:
            batch_cat_override = st.selectbox(
                "Optional Category Override for Selected",
                options=["(Use row category)"] + category_list,
                label_visibility="collapsed",
            )
        with act_col2:
            batch_rec_override = st.selectbox(
                "Expense Frequency for Selected",
                options=["(Use row frequency)", "One-Time", "Recurring"],
                label_visibility="collapsed",
            )
        with act_col3:
            batch_note = st.text_input(
                "Shared Audit Note / Rationale (Optional)",
                placeholder="Optional rationale for all selected transactions...",
                label_visibility="collapsed",
            )

        def _apply_batch_verdict(target_verdict: str, default_note: str) -> None:
            cat_arg = None if batch_cat_override == "(Use row category)" else batch_cat_override
            rec_arg = None if batch_rec_override == "(Use row frequency)" else batch_rec_override
            if cat_arg is not None and rec_arg is not None:
                bulk_update_transactions_by_ids(
                    selected_ids,
                    target_verdict,
                    category=cat_arg,
                    recurrence=rec_arg,
                    user_excuse=batch_note or default_note,
                )
            else:
                for _, srow in selected_rows.iterrows():
                    row_cat = cat_arg if cat_arg is not None else str(srow["category"])
                    row_rec = rec_arg if rec_arg is not None else str(srow["recurrence"])
                    bulk_update_transactions_by_ids(
                        [int(srow["id"])],
                        target_verdict,
                        category=row_cat,
                        recurrence=row_rec,
                        user_excuse=batch_note or default_note,
                    )

        mb1, mb2, mb3, mb4 = st.columns(4)
        with mb1:
            if st.button(f"Mark Selected Justified ({len(selected_ids)})", width="stretch", disabled=len(selected_ids) == 0):
                _apply_batch_verdict("Justified", "Batch verified as justified.")
                st.session_state["batch_select_all"] = False
                st.session_state["batch_ed_ver"] += 1
                trigger_auto_github_sync("batch mark justified")
                st.rerun()
        with mb2:
            if st.button(f"Mark Selected Unjustified ({len(selected_ids)})", width="stretch", disabled=len(selected_ids) == 0):
                _apply_batch_verdict("Guilty / Bad Purchase", "Batch marked unjustified.")
                st.session_state["batch_select_all"] = False
                st.session_state["batch_ed_ver"] += 1
                trigger_auto_github_sync("batch mark unjustified")
                st.rerun()
        with mb3:
            if st.button(f"Mark Selected Essential ({len(selected_ids)})", width="stretch", disabled=len(selected_ids) == 0):
                _apply_batch_verdict("Essential Pass", "Batch marked essential.")
                st.session_state["batch_select_all"] = False
                st.session_state["batch_ed_ver"] += 1
                trigger_auto_github_sync("batch mark essential")
                st.rerun()
        with mb4:
            if st.button(f"Delete Selected ({len(selected_ids)})", width="stretch", disabled=len(selected_ids) == 0):
                bulk_delete_transactions_by_ids(selected_ids)
                st.session_state["batch_select_all"] = False
                st.session_state["batch_ed_ver"] += 1
                trigger_auto_github_sync("batch delete")
                st.rerun()

    else:
        col_list, col_chat = st.columns([1.0, 1.5], gap="large")

        with col_list:
            st.markdown(f"##### {audit_queue_mode} ({len(suspect_choices_df)})")
            options_map = {
                f"[#{row['id']}]  {row['tx_date']}  ·  {row['merchant']}  ·  €{abs(row['amount']):.2f}": row["id"]
                for _, row in suspect_choices_df.iterrows()
            }
            selected_label = st.radio(
                "Select transaction",
                options=list(options_map.keys()),
                index=0,
                label_visibility="collapsed",
            )
            selected_tx_id = options_map[selected_label]
            tx_row = suspect_choices_df[suspect_choices_df["id"] == selected_tx_id].iloc[0]

            opp_tx = compute_opportunity_cost(tx_row["amount"], hourly_wage=hourly_wage)
            current_rec_val = tx_row["recurrence"] if tx_row.get("recurrence") in ("One-Time", "Recurring") else "One-Time"
            st.markdown(
                f"""
                <div class="spec-card">
                    <div class="spec-label">Transaction #{tx_row['id']} · {tx_row['verdict']} · {current_rec_val}</div>
                    <div style="font-size:1.05rem; font-weight:500; color:#F4F4F6; margin:4px 0;">{tx_row['merchant']}</div>
                    <div style="font-size:0.8rem; color:#7D7D87; margin-bottom:12px;">{tx_row['description']}</div>
                    <div class="spec-grid">
                        <div>
                            <div class="spec-label">Amount</div>
                            <div class="spec-value">€{opp_tx['amount']:.2f}</div>
                        </div>
                        <div>
                            <div class="spec-label">Labor Cost</div>
                            <div class="spec-value">{opp_tx['hours_worked']}h</div>
                        </div>
                        <div>
                            <div class="spec-label">10Y Compounded</div>
                            <div class="spec-value">€{opp_tx['fv_10y']:.2f}</div>
                        </div>
                        <div>
                            <div class="spec-label">20Y Compounded</div>
                            <div class="spec-value">€{opp_tx['fv_20y']:.2f}</div>
                        </div>
                    </div>
                </div>
                """,
                unsafe_allow_html=True,
            )

            new_cat = st.selectbox(
                "Category",
                options=category_list,
                index=category_list.index(tx_row["category"]) if tx_row["category"] in category_list else 0,
                key=f"cat_edit_{selected_tx_id}",
            )
            new_rec = st.radio(
                "Is this a One-Time or Recurring Expense?",
                options=["One-Time", "Recurring"],
                index=1 if current_rec_val == "Recurring" else 0,
                horizontal=True,
                key=f"rec_edit_{selected_tx_id}",
            )
            if new_rec != current_rec_val or new_cat != tx_row["category"]:
                update_transaction_verdict(
                    tx_id=int(selected_tx_id),
                    verdict=tx_row["verdict"],
                    regret_score=int(tx_row["regret_score"]),
                    user_excuse=tx_row["user_excuse"],
                    ai_roast=tx_row["ai_roast"],
                    interrogation_history=json.loads(tx_row["interrogation_history"] or "[]"),
                    category=new_cat,
                    recurrence=new_rec,
                )
                trigger_auto_github_sync("update tx frequency/category")
                st.rerun()

        with col_chat:
            st.markdown(f"##### Review — {tx_row['merchant']} (€{abs(tx_row['amount']):.2f})")

            try:
                conv_history: list = json.loads(tx_row["interrogation_history"] or "[]")
            except Exception:
                conv_history = []

            if not conv_history:
                opening_msg, meta = interrogate_transaction(
                    merchant=tx_row["merchant"],
                    description=tx_row["description"],
                    amount=tx_row["amount"],
                    category=new_cat,
                    tx_date=tx_row["tx_date"],
                    conversation=[],
                    provider=provider_choice,
                    model=ai_model,
                    api_key=st.session_state.get("user_api_key", ""),
                    strictness=strictness_choice,
                    hourly_wage=hourly_wage,
                    monthly_savings_goal=monthly_savings_goal,
                    recurrence=new_rec,
                )
                conv_history = [{"role": "assistant", "content": opening_msg}]
                update_transaction_verdict(
                    tx_id=int(selected_tx_id),
                    verdict=tx_row["verdict"],
                    regret_score=int(meta.get("regret_score", 70)),
                    user_excuse=tx_row["user_excuse"],
                    ai_roast=str(meta.get("one_line_roast", opening_msg[:110])),
                    interrogation_history=conv_history,
                    category=new_cat,
                    recurrence=new_rec,
                )

            chat_container = st.container(height=340)
            with chat_container:
                for msg in conv_history:
                    with st.chat_message(msg["role"]):
                        st.markdown(msg["content"])

            defense_input = st.chat_input("Enter justification (and whether one-time or recurring)...")
            if defense_input:
                conv_history.append({"role": "user", "content": defense_input})
                ai_reply, meta = interrogate_transaction(
                    merchant=tx_row["merchant"],
                    description=tx_row["description"],
                    amount=tx_row["amount"],
                    category=new_cat,
                    tx_date=tx_row["tx_date"],
                    conversation=conv_history,
                    provider=provider_choice,
                    model=ai_model,
                    api_key=st.session_state.get("user_api_key", ""),
                    strictness=strictness_choice,
                    hourly_wage=hourly_wage,
                    monthly_savings_goal=monthly_savings_goal,
                    recurrence=new_rec,
                )
                conv_history.append({"role": "assistant", "content": ai_reply})
                rec_verdict = str(meta.get("verdict_recommendation", "Pending Review"))
                rec_freq = str(meta.get("recurrence_recommendation", new_rec))
                rec_score = int(meta.get("regret_score", 70))
                rec_roast = str(meta.get("one_line_roast", ai_reply[:110]))

                update_transaction_verdict(
                    tx_id=int(selected_tx_id),
                    verdict=rec_verdict,
                    regret_score=rec_score,
                    user_excuse=defense_input,
                    ai_roast=rec_roast,
                    interrogation_history=conv_history,
                    category=new_cat,
                    recurrence=rec_freq,
                )
                trigger_auto_github_sync("audit review")
                st.rerun()

            b_col1, b_col2, b_col3, b_col4 = st.columns(4)
            with b_col1:
                if st.button("Mark Unjustified", width="stretch"):
                    update_transaction_verdict(
                        tx_id=int(selected_tx_id),
                        verdict="Guilty / Bad Purchase",
                        regret_score=90,
                        user_excuse=tx_row["user_excuse"] or "Acknowledged as unjustified.",
                        ai_roast=f"Unjustified spend ({new_rec} · {opp_tx['hours_worked']}h labor).",
                        interrogation_history=conv_history,
                        category=new_cat,
                        recurrence=new_rec,
                    )
                    trigger_auto_github_sync("mark unjustified")
                    st.rerun()
            with b_col2:
                if st.button("Mark Justified", width="stretch"):
                    update_transaction_verdict(
                        tx_id=int(selected_tx_id),
                        verdict="Justified",
                        regret_score=15,
                        user_excuse=tx_row["user_excuse"] or "Verified intentional purchase.",
                        ai_roast=tx_row["ai_roast"] or f"Verified by user ({new_rec}).",
                        interrogation_history=conv_history,
                        category=new_cat,
                        recurrence=new_rec,
                    )
                    trigger_auto_github_sync("mark justified")
                    st.rerun()
            with b_col3:
                if st.button("Essential Pass", width="stretch"):
                    update_transaction_verdict(
                        tx_id=int(selected_tx_id),
                        verdict="Essential Pass",
                        regret_score=0,
                        user_excuse="Essential expense.",
                        ai_roast=f"Essential operating expense ({new_rec}).",
                        interrogation_history=conv_history,
                        category=new_cat,
                        recurrence=new_rec,
                    )
                    trigger_auto_github_sync("mark essential")
                    st.rerun()
            with b_col4:
                if st.button("Delete", width="stretch"):
                    delete_transaction(int(selected_tx_id))
                    trigger_auto_github_sync("delete tx")
                    st.rerun()


# ==============================================================================
# TAB 5: BPER BANK IMPORTER
# ==============================================================================
with tabs[4]:
    st.markdown("##### BPER & Banca Popolare di Sondrio Statement Import")
    st.caption(
        "Upload BPER PDF statements (`LQ10_*.pdf` Mod. 05.13.0011), Banca Popolare di Sondrio / BPER Group statements (`HC42_*.pdf` Estratto Conto), "
        "or `.xlsx`/`.csv` exports — or scan the workspace directory directly. Duplicate entries are skipped via SHA-256 hashing."
    )

    workspace_dir = os.path.dirname(os.path.abspath(__file__))
    local_pdfs = scan_workspace_bper_pdfs(workspace_dir)

    imp_col1, imp_col2 = st.columns([1.4, 1.0], gap="large")
    with imp_col1:
        uploaded_bper_files = st.file_uploader(
            "Select BPER statement files (.pdf, .xlsx, .xls, .csv)",
            type=["pdf", "xlsx", "xls", "csv"],
            accept_multiple_files=True,
        )
    with imp_col2:
        st.markdown("<div class='spec-label' style='margin-top:6px;'>Workspace Statements</div>", unsafe_allow_html=True)
        if local_pdfs:
            pdf_names = ", ".join(os.path.basename(p) for p in local_pdfs)
            st.caption(f"Detected {len(local_pdfs)} PDF statements in folder: {pdf_names}")
            if st.button(f"Scan & Preview {len(local_pdfs)} Folder PDFs", width="stretch"):
                parsed_df, msg = parse_multiple_bper_pdfs(local_pdfs, suspect_threshold=suspect_threshold)
                st.session_state["bper_preview_df"] = parsed_df
                st.session_state["bper_preview_msg"] = msg
        else:
            st.caption("No `.pdf` files detected in the root directory.")

    if uploaded_bper_files:
        frames = []
        for uf in uploaded_bper_files:
            p_df, _ = parse_bper_file(uf, suspect_threshold=suspect_threshold)
            if not p_df.empty:
                frames.append(p_df)
        if frames:
            combined_up = pd.concat(frames, ignore_index=True).sort_values("Date", ascending=False).reset_index(drop=True)
            st.session_state["bper_preview_df"] = combined_up
            st.session_state["bper_preview_msg"] = f"Parsed {len(combined_up)} transactions from {len(frames)} uploaded file(s)."

    if "bper_preview_df" in st.session_state and not st.session_state["bper_preview_df"].empty:
        st.caption(st.session_state.get("bper_preview_msg", ""))
        edited_bper_df = st.data_editor(
            st.session_state["bper_preview_df"],
            width="stretch",
            hide_index=True,
            column_config={
                "Include": st.column_config.CheckboxColumn("Import", default=True),
                "Amount (€)": st.column_config.NumberColumn("Amount", format="€ %.2f"),
                "Category": st.column_config.SelectboxColumn("Category", options=category_list),
                "Recurrence": st.column_config.SelectboxColumn("Frequency", options=["One-Time", "Recurring"]),
                "Status / Verdict": st.column_config.SelectboxColumn(
                    "Classification",
                    options=["Pending Review", "Essential Pass", "Justified", "Guilty / Bad Purchase", "Income"],
                ),
            },
        )

        if st.button("Commit Selected Transactions", width="stretch"):
            inserted_cnt = 0
            skipped_cnt = 0

            for _, row in edited_bper_df.iterrows():
                if not row.get("Include", True):
                    continue
                amt = float(row["Amount (€)"])
                verdict = str(row["Status / Verdict"])
                rec_val = str(row.get("Recurrence", "One-Time"))
                opp = compute_opportunity_cost(amt, hourly_wage=hourly_wage)
                roast = (
                    f"Statement import ({rec_val} · {opp['hours_worked']}h labor). Pending review."
                    if verdict == "Pending Review"
                    else f"Statement import ({rec_val})."
                )
                regret = 70 if verdict == "Pending Review" else (85 if verdict == "Guilty / Bad Purchase" else 5)

                ok, _ = add_transaction(
                    tx_date=str(row["Date"]),
                    valuta_date=str(row["Valuta"]),
                    description=str(row["Description"]),
                    merchant=str(row["Merchant"]),
                    amount=amt,
                    category=str(row["Category"]),
                    source="Bank PDF",
                    verdict=verdict,
                    regret_score=regret,
                    ai_roast=roast,
                    recurrence=rec_val,
                    allow_duplicate_manual=False,
                )
                if ok:
                    inserted_cnt += 1
                else:
                    skipped_cnt += 1

            del st.session_state["bper_preview_df"]
            trigger_auto_github_sync("Bank PDF import")
            st.toast(f"Imported {inserted_cnt} transactions ({skipped_cnt} duplicates skipped).")
            st.rerun()


# ==============================================================================
# TAB 6: HOLDING VAULT (24-HOUR COOLING-OFF)
# ==============================================================================
with tabs[5]:
    v_col1, v_col2 = st.columns([1.0, 1.3], gap="large")
    with v_col1:
        st.markdown("##### 24-Hour Holding Vault")
        st.caption("Defer non-essential purchases for 24 hours before committing capital.")
        with st.form("wishlist_form", clear_on_submit=True):
            w_item = st.text_input("Item", placeholder="e.g. Headphones, Coat...")
            w_price = st.number_input("Price (EUR)", min_value=1.0, max_value=50000.0, value=69.90, step=1.0, format="%.2f")
            w_cat = st.selectbox("Category", options=category_list, index=6)
            w_reason = st.text_area("Rationale", placeholder="Why are you considering this item?", height=68)
            w_submit = st.form_submit_button("Place in Holding Vault", width="stretch")

        if w_submit and w_item.strip():
            opp_w = compute_opportunity_cost(w_price, hourly_wage=hourly_wage)
            warning_msg = (
                f"€{w_price:.2f} requires {opp_w['hours_worked']} hours of net labor "
                f"and compounds to €{opp_w['fv_10y']:.2f} over 10 years."
            )
            unlock_iso = (datetime.now() + timedelta(hours=24)).isoformat(timespec="minutes")
            add_to_wishlist(
                item_name=w_item,
                price=w_price,
                category=w_cat,
                urge_reason=w_reason,
                ai_initial_warning=warning_msg,
                unlock_at=unlock_iso,
            )
            trigger_auto_github_sync("holding vault entry")
            st.rerun()

    with v_col2:
        st.markdown("##### Held Items")
        vault_df = get_wishlist_df()
        if vault_df.empty:
            st.caption("No items currently in the holding vault.")
        else:
            for _, vrow in vault_df.iterrows():
                st.markdown(
                    f"""
                    <div class="spec-card">
                        <div class="spec-label">{vrow['category']} · {vrow['status']}</div>
                        <div style="display:flex; justify-content:space-between; align-items:baseline; margin:4px 0;">
                            <span style="font-weight:500; color:#F4F4F6;">{vrow['item_name']}</span>
                            <span class="spec-value">€{vrow['price']:.2f}</span>
                        </div>
                        <div style="font-size:0.82rem; color:#8A8A93;">{vrow['ai_initial_warning']}</div>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )
                if vrow["status"] == "Locked":
                    vc1, vc2 = st.columns(2)
                    with vc1:
                        if st.button(f"Cancel Purchase (€{vrow['price']:.2f} Saved)", key=f"skip_{vrow['id']}", width="stretch"):
                            update_wishlist_status(int(vrow["id"]), "Skipped & Saved")
                            trigger_auto_github_sync("vault item skipped")
                            st.rerun()
                    with vc2:
                        if st.button("Record as Purchased", key=f"buy_{vrow['id']}", width="stretch"):
                            update_wishlist_status(int(vrow["id"]), "Bought Anyway")
                            add_transaction(
                                tx_date=date.today().strftime("%Y-%m-%d"),
                                description=f"Holding Vault: {vrow['item_name']}",
                                merchant=vrow["item_name"],
                                amount=-abs(float(vrow["price"])),
                                category=vrow["category"],
                                source="Holding Vault",
                                verdict="Pending Review",
                                regret_score=75,
                                user_excuse=vrow["urge_reason"],
                                ai_roast=vrow["ai_initial_warning"],
                            )
                            trigger_auto_github_sync("vault item purchased")
                            st.rerun()


# ==============================================================================
# TAB 7: SETTINGS
# ==============================================================================
with tabs[6]:
    s_col1, s_col2 = st.columns(2, gap="large")
    with s_col1:
        st.markdown("##### Financial Parameters")
        with st.form("settings_form"):
            new_wage = st.number_input(
                "Net Hourly Wage (EUR)",
                min_value=1.0,
                max_value=500.0,
                value=hourly_wage,
                step=0.5,
            )
            new_income = st.number_input(
                "Monthly Net Income Target (EUR)",
                min_value=0.0,
                max_value=100000.0,
                value=monthly_income_target,
                step=50.0,
            )
            new_goal = st.number_input(
                "Monthly Savings Target (EUR)",
                min_value=0.0,
                max_value=100000.0,
                value=monthly_savings_goal,
                step=50.0,
            )
            new_thresh = st.number_input(
                "Audit Threshold for Uncategorized Spend (EUR)",
                min_value=1.0,
                max_value=1000.0,
                value=suspect_threshold,
                step=1.0,
            )
            new_pac = st.number_input(
                "Monthly Stock PAC — SOTTOSCRIZIONI FONDI E SICAV (EUR/mo)",
                min_value=0.0,
                max_value=10000.0,
                value=monthly_pac_fondi_eur,
                step=10.0,
            )
            new_wise_inr = st.number_input(
                "Wise Transfer (>€300) Investment Allocation (INR per transfer)",
                min_value=0.0,
                max_value=1000000.0,
                value=wise_invest_inr_per_300,
                step=500.0,
            )
            new_fx = st.number_input(
                "EUR / INR Exchange Rate",
                min_value=1.0,
                max_value=500.0,
                value=eur_inr_rate,
                step=0.5,
            )
            if st.form_submit_button("Save Parameters", width="stretch"):
                set_setting("hourly_wage", str(new_wage))
                set_setting("monthly_income_target", str(new_income))
                set_setting("monthly_savings_goal", str(new_goal))
                set_setting("suspect_threshold_eur", str(new_thresh))
                set_setting("monthly_pac_fondi_eur", str(new_pac))
                set_setting("wise_invest_inr_per_300", str(new_wise_inr))
                set_setting("eur_inr_rate", str(new_fx))
                trigger_auto_github_sync("update settings")
                st.rerun()

    with s_col2:
        st.markdown("##### Category Allocations")
        edited_cats = st.data_editor(
            categories_df,
            width="stretch",
            hide_index=True,
            disabled=["name"],
            column_config={
                "name": "Category",
                "tier": st.column_config.SelectboxColumn(
                    "Tier", options=["Essential", "Discretionary", "Impulse", "Savings", "Income"]
                ),
                "monthly_limit": st.column_config.NumberColumn("Monthly Limit", format="€ %.2f"),
            },
        )
        if st.button("Save Allocations", width="stretch"):
            for _, crow in edited_cats.iterrows():
                update_category_budget(crow["name"], crow["tier"], float(crow["monthly_limit"]))
            trigger_auto_github_sync("update allocations")
            st.rerun()
