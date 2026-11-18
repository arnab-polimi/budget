from typing import Dict, List, Any, Optional
import pandas as pd


def compute_financial_intelligence(
    all_tx_df: pd.DataFrame,
    hourly_wage: float = 14.0,
    custom_cut_ratios: Optional[Dict[str, float]] = None,
    include_justified_in_leaks: bool = False,
    eur_inr_rate: float = 90.0,
    wise_invest_inr_per_300: float = 12000.0,
    monthly_pac_fondi_eur: float = 100.0,
) -> Dict[str, Any]:
    """
    Computes an audit-reactive Financial Wisdom Score (0-100), monthly cashflow breakdown,
    exact merchant-by-merchant recoverable savings (annual/YTD and per month),
    and a concrete monthly savings prescription that separates Recurring vs. One-Time expenses
    AND credits automated investments:
      - Every Wise transfer > €300 includes `wise_invest_inr_per_300` (12,000 INR) invested.
      - Monthly €100 stock/fund investments ("SOTTOSCRIZIONI FONDI E SICAV" / `monthly_pac_fondi_eur`).
    """
    if all_tx_df.empty:
        return {"empty": True}

    cut_ratios = {
        "bnpl": 0.75,
        "revolut": 0.50,
        "retail": 0.50,
        "amazon": 0.60,
        "delivery": 0.80,
        "dining": 0.40,
        "paypal_sdd": 0.60,
        "bper_fees": 1.00,
    }
    if custom_cut_ratios:
        cut_ratios.update(custom_cut_ratios)

    df = all_tx_df.copy()
    if "recurrence" not in df.columns:
        df["recurrence"] = "One-Time"
    df["recurrence"] = df["recurrence"].fillna("One-Time")

    df["month"] = df["tx_date"].str.slice(0, 7)
    months = sorted(df["month"].dropna().unique().tolist())
    n_months = max(len(months), 1)

    inflow_df = df[df["amount"] > 0].copy()
    outflow_df = df[df["amount"] < 0].copy()
    outflow_df["abs_amt"] = outflow_df["amount"].abs()

    total_inflow = float(inflow_df["amount"].sum())
    total_outflow = float(outflow_df["abs_amt"].sum())
    net_retained = total_inflow - total_outflow

    # --- Investment & Stock Savings Recognition ---
    # 1. Every Wise transfer > €300 allocates 12,000 INR (~€133.33 at 90 INR/EUR) into investments
    safe_fx = max(float(eur_inr_rate), 1.0)
    wise_invest_per_tx_eur = float(wise_invest_inr_per_300) / safe_fx
    wise_all_df = outflow_df[outflow_df["merchant"].str.contains("Wise", case=False, na=False)]
    wise_gt300_df = wise_all_df[wise_all_df["abs_amt"] > 300.0]
    wise_gt300_cnt = int(len(wise_gt300_df))
    wise_invested_total_inr = wise_gt300_cnt * float(wise_invest_inr_per_300)
    wise_invested_total_eur = wise_gt300_cnt * wise_invest_per_tx_eur

    # 2. "SOTTOSCRIZIONI FONDI E SICAV" (€100/month into stock/equity funds)
    fondi_mask = (
        (outflow_df["category"] == "Savings & Investments")
        | (outflow_df["merchant"].str.contains("PAC Fondi|Etica", case=False, na=False))
        | (outflow_df["description"].str.contains("SOTTOSCRIZIONI FONDI|SOTTOSCRIZIONE ETICA", case=False, na=False))
    )
    fondi_df = outflow_df[fondi_mask]
    explicit_fondi_by_m = fondi_df.groupby("month")["abs_amt"].sum()

    # For each month in the dataset: use explicit SOTTOSCRIZIONI FONDI E SICAV if present in statement
    # (e.g. HC42 Estratto Conto), or credit the recurring €100/mo stock PAC (`monthly_pac_fondi_eur`)
    # on LQ10 payment-only summaries where securities debits are omitted
    m_wise_inv = wise_gt300_df.groupby("month")["abs_amt"].count() * wise_invest_per_tx_eur
    m_fondi_inv: Dict[str, float] = {}
    for m in months:
        exp_val = float(explicit_fondi_by_m.get(m, 0.0))
        m_fondi_inv[m] = exp_val if exp_val > 0 else float(monthly_pac_fondi_eur)

    fondi_explicit_eur = float(fondi_df["abs_amt"].sum())
    fondi_total_accredited_eur = sum(m_fondi_inv.values())
    total_invested_capital_eur = wise_invested_total_eur + fondi_total_accredited_eur
    monthly_invested_avg_eur = total_invested_capital_eur / n_months

    # True Wealth / Capital Accumulation = Net Cash Retained + Active Investments (Fondi + Wise 12k INR)
    # Note: explicit Fondi rows & Wise >€300 rows were already subtracted in total_outflow, so adding them back
    # measures true net wealth retained + invested!
    true_wealth_accumulated_eur = net_retained + wise_invested_total_eur + fondi_explicit_eur
    savings_rate_pct = (true_wealth_accumulated_eur / total_inflow * 100.0) if total_inflow > 0 else 0.0
    cash_only_savings_rate_pct = (net_retained / total_inflow * 100.0) if total_inflow > 0 else 0.0

    # Recurring vs One-Time Outflow Breakdown
    recurring_out_df = outflow_df[outflow_df["recurrence"] == "Recurring"]
    onetime_out_df = outflow_df[outflow_df["recurrence"] != "Recurring"]
    recurring_out_total = float(recurring_out_df["abs_amt"].sum())
    onetime_out_total = float(onetime_out_df["abs_amt"].sum())
    recurring_monthly_burn = recurring_out_total / n_months
    onetime_monthly_avg = onetime_out_total / n_months

    # Audit progress metrics
    non_essential_df = outflow_df[outflow_df["verdict"] != "Essential Pass"]
    total_audit_pool_cnt = len(non_essential_df)
    pending_cnt = int((outflow_df["verdict"] == "Pending Review").sum())
    justified_cnt = int((outflow_df["verdict"] == "Justified").sum())
    guilty_cnt = int((outflow_df["verdict"] == "Guilty / Bad Purchase").sum())
    essential_cnt = int((outflow_df["verdict"] == "Essential Pass").sum())

    pending_eur = float(outflow_df[outflow_df["verdict"] == "Pending Review"]["abs_amt"].sum())
    justified_eur = float(outflow_df[outflow_df["verdict"] == "Justified"]["abs_amt"].sum())
    guilty_eur = float(outflow_df[outflow_df["verdict"] == "Guilty / Bad Purchase"]["abs_amt"].sum())

    reviewed_cnt = justified_cnt + guilty_cnt
    audit_completion_pct = (reviewed_cnt / max(total_audit_pool_cnt, 1)) * 100.0

    # Recurring base salary estimation
    salary_rows = inflow_df[inflow_df["category"] == "Income / Salary"]
    monthly_salary_by_m = salary_rows.groupby("month")["amount"].sum()
    base_monthly_income = (
        float(monthly_salary_by_m.median()) if not monthly_salary_by_m.empty else (total_inflow / n_months)
    )
    avg_monthly_inflow = total_inflow / n_months
    avg_monthly_outflow = total_outflow / n_months

    # Monthly cashflow table
    m_in = inflow_df.groupby("month")["amount"].sum()
    m_out = outflow_df.groupby("month")["abs_amt"].sum()

    essential_mask = outflow_df["verdict"] == "Essential Pass"
    transfer_mask = outflow_df["category"] == "Transfers & P2P (Satispay/Revolut/BancomatPay)"
    discretionary_mask = (~essential_mask) & (~transfer_mask)

    m_ess = outflow_df[essential_mask].groupby("month")["abs_amt"].sum()
    m_disc = outflow_df[discretionary_mask].groupby("month")["abs_amt"].sum()
    m_trans = outflow_df[transfer_mask].groupby("month")["abs_amt"].sum()
    m_rec = recurring_out_df.groupby("month")["abs_amt"].sum()
    m_one = onetime_out_df.groupby("month")["abs_amt"].sum()

    monthly_rows = []
    deficit_months = 0
    for m in months:
        inc = float(m_in.get(m, 0.0))
        out = float(m_out.get(m, 0.0))
        ess = float(m_ess.get(m, 0.0))
        disc = float(m_disc.get(m, 0.0))
        trn = float(m_trans.get(m, 0.0))
        rec_m = float(m_rec.get(m, 0.0))
        one_m = float(m_one.get(m, 0.0))
        wise_inv_m = float(m_wise_inv.get(m, 0.0))
        fondi_inv_m = float(m_fondi_inv.get(m, 0.0))
        explicit_fondi_m = float(explicit_fondi_by_m.get(m, 0.0))
        invested_m = wise_inv_m + fondi_inv_m
        net = inc - out
        # True wealth change adds back investments that were deducted inside outflow
        true_net_wealth_m = net + wise_inv_m + explicit_fondi_m
        if true_net_wealth_m < 0:
            deficit_months += 1
        sr = (true_net_wealth_m / inc * 100.0) if inc > 0 else 0.0
        monthly_rows.append(
            {
                "Month": m,
                "Inflow (€)": round(inc, 2),
                "Invested (Fondi + Wise 12k INR) (€)": round(invested_m, 2),
                "Recurring Outflow (€)": round(rec_m, 2),
                "One-Time Outflow (€)": round(one_m, 2),
                "Essential (€)": round(ess, 2),
                "Discretionary & Retail (€)": round(disc, 2),
                "Transfers & P2P (€)": round(trn, 2),
                "Total Outflow (€)": round(out, 2),
                "Net Cashflow (€)": round(net, 2),
                "Net Wealth Retained + Invested (€)": round(true_net_wealth_m, 2),
                "Effective Savings Rate (%)": round(sr, 1),
            }
        )
    monthly_summary_df = pd.DataFrame(monthly_rows)

    # Year-over-Year Comparison Table (e.g. 2025 vs 2026)
    yearly_rows = []
    if not monthly_summary_df.empty:
        ms_tmp = monthly_summary_df.copy()
        ms_tmp["Year"] = ms_tmp["Month"].str.slice(0, 4)
        for yr, grp in ms_tmp.groupby("Year"):
            ym_cnt = len(grp)
            y_in = float(grp["Inflow (€)"].sum())
            y_out = float(grp["Total Outflow (€)"].sum())
            y_inv = float(grp["Invested (Fondi + Wise 12k INR) (€)"].sum())
            y_wealth = float(grp["Net Wealth Retained + Invested (€)"].sum())
            y_rec_avg = float(grp["Recurring Outflow (€)"].mean())
            y_one_avg = float(grp["One-Time Outflow (€)"].mean())
            y_sr = (y_wealth / y_in * 100.0) if y_in > 0 else 0.0
            yearly_rows.append(
                {
                    "Year": yr,
                    "Months": ym_cnt,
                    "Inflow (€)": round(y_in, 2),
                    "Avg Inflow/mo (€)": round(y_in / ym_cnt, 2),
                    "Total Outflow (€)": round(y_out, 2),
                    "Avg Recurring/mo (€)": round(y_rec_avg, 2),
                    "Avg One-Time/mo (€)": round(y_one_avg, 2),
                    "Invested (PAC + Wise) (€)": round(y_inv, 2),
                    "Net Wealth (+Invested) (€)": round(y_wealth, 2),
                    "Effective Save Rate (%)": round(y_sr, 1),
                }
            )
    yearly_comparison_df = pd.DataFrame(yearly_rows)

    # Specific Leak Analysis (Reactive to Audit Verdicts + Recurrence + Interactive Sliders!)
    leaks: List[Dict[str, Any]] = []

    def _add_audit_reactive_leak(
        key: str,
        place: str,
        category: str,
        subset: pd.DataFrame,
        default_ratio: float,
        action_rule: str,
        is_fee_channel: bool = False,
        net_offset_eur: float = 0.0,
    ) -> None:
        if subset.empty:
            return

        total_channel_spent = float(subset["abs_amt"].sum())
        rec_spent = float(subset[subset["recurrence"] == "Recurring"]["abs_amt"].sum())
        one_spent = float(subset[subset["recurrence"] != "Recurring"]["abs_amt"].sum())

        cleared_sub = subset[subset["verdict"].isin(["Justified", "Essential Pass"])] if not is_fee_channel else pd.DataFrame()
        guilty_sub = subset[subset["verdict"] == "Guilty / Bad Purchase"]
        pending_sub = subset[subset["verdict"] == "Pending Review"] if not is_fee_channel else subset

        cleared_amt = float(cleared_sub["abs_amt"].sum()) if not cleared_sub.empty else 0.0
        guilty_amt = float(guilty_sub["abs_amt"].sum()) if not guilty_sub.empty else 0.0
        pending_amt = float(pending_sub["abs_amt"].sum()) if not pending_sub.empty else 0.0

        # Active leak base: if include_justified_in_leaks is False, cleared ('Justified'/'Essential') spends are excluded!
        if include_justified_in_leaks or is_fee_channel:
            leak_base = max(0.0, total_channel_spent - net_offset_eur)
            recoverable_total = leak_base * default_ratio
        else:
            effective_pending = max(0.0, pending_amt - net_offset_eur)
            recoverable_total = (guilty_amt * max(default_ratio, 0.90)) + (effective_pending * default_ratio)

        # Split recoverable into Recurring vs One-Time proportional to their share in the channel
        rec_share = (rec_spent / total_channel_spent) if total_channel_spent > 0 else 0.0
        rec_recoverable_monthly = (recoverable_total * rec_share) / n_months
        one_recoverable_monthly = (recoverable_total * (1.0 - rec_share)) / n_months

        recoverable_monthly = recoverable_total / n_months
        hours_lost = recoverable_total / max(hourly_wage, 1.0)
        fv_10y = recoverable_total * ((1.08) ** 10)

        freq_label = "Recurring" if rec_share >= 0.65 else ("One-Time" if rec_share <= 0.35 else "Mixed")

        leaks.append(
            {
                "key": key,
                "Where (Merchant / Channel)": place,
                "Category": category,
                "Pattern": freq_label,
                "Tx Count": int(len(subset)),
                "Total Spent (€)": round(total_channel_spent, 2),
                "Recurring (€)": round(rec_spent, 2),
                "One-Time (€)": round(one_spent, 2),
                "Cleared / Justified (€)": round(cleared_amt, 2),
                "Unjustified / Pending (€)": round(guilty_amt + pending_amt, 2),
                "Target Cut (%)": int(round(default_ratio * 100)),
                "Saveable This Period (€)": round(recoverable_total, 2),
                "Saveable Per Month (€/mo)": round(recoverable_monthly, 2),
                "rec_save_mo": round(rec_recoverable_monthly, 2),
                "one_save_mo": round(one_recoverable_monthly, 2),
                "Labor Equivalent (h)": round(hours_lost, 1),
                "10Y Compounded (€)": round(fv_10y, 2),
                "Audit Prescription": action_rule,
            }
        )

    # 1. PayPal Online Shopping & Paga in 3 Rate (BNPL) (excludes items reclassified to Travel/Essential etc.)
    bnpl_df = outflow_df[
        (outflow_df["category"] == "Online Shopping & PayPal")
        & (~outflow_df["merchant"].isin(["PayPal SDD", "Commissione BPER (PayPal SDD)"]))
    ]
    _add_audit_reactive_leak(
        "bnpl",
        "PayPal Online Shopping & Paga in 3 Rate (BNPL)",
        "Online Shopping & PayPal",
        bnpl_df,
        default_ratio=cut_ratios["bnpl"],
        action_rule="Eliminate BNPL installments & PayPal checkouts; use 24h Holding Vault before any >€30 purchase.",
    )

    # 2. Revolut Top-Ups (net of Revolut inbound returns)
    rev_out_df = outflow_df[outflow_df["merchant"] == "Revolut Top-Up / Transfer"]
    rev_in_sum = float(inflow_df[inflow_df["merchant"] == "Revolut (Inbound Transfer)"]["amount"].sum())
    _add_audit_reactive_leak(
        "revolut",
        f"Revolut Top-Ups (€{rev_in_sum:.0f} returned to BPER)",
        "Transfers & P2P",
        rev_out_df,
        default_ratio=cut_ratios["revolut"],
        action_rule="Cap unreturned Revolut pocket-money transfers instead of frequent €20–€50 top-ups.",
        net_offset_eur=rev_in_sum,
    )

    # 3. Retail Apparel & Sports (Decathlon, PUMA Outlet, OVS, MediaWorld, Tiger, Full Trend)
    retail_merchants = [
        "Decathlon",
        "PUMA Outlet Torino - Settimo Torin",
        "OVS TORINO",
        "MediaWorld",
        "TIGER STORE MILANO PO.",
        "TIGER STORE AEROPORTO. CASELLE TORIN",
        "FULL TREND S.R.L.",
    ]
    ret_df = outflow_df[outflow_df["merchant"].isin(retail_merchants)]
    _add_audit_reactive_leak(
        "retail",
        "Decathlon, PUMA, OVS & MediaWorld",
        "Shopping, Clothes & Amazon",
        ret_df,
        default_ratio=cut_ratios["retail"],
        action_rule="Enforce a strict monthly clothing & gear envelope across physical retail stores.",
    )

    # 4. Amazon
    amz_df = outflow_df[outflow_df["merchant"] == "Amazon"]
    _add_audit_reactive_leak(
        "amazon",
        "Amazon",
        "Shopping, Clothes & Amazon",
        amz_df,
        default_ratio=cut_ratios["amazon"],
        action_rule="Batch non-urgent orders once a month rather than separate checkout impulses.",
    )

    # 5. Glovo & Fast Food Delivery
    glovo_df = outflow_df[outflow_df["category"] == "Food Delivery (Glovo/Deliveroo/JustEat)"]
    _add_audit_reactive_leak(
        "delivery",
        "Glovo & Takeout (Olimpico Kebab, etc.)",
        "Food Delivery",
        glovo_df,
        default_ratio=cut_ratios["delivery"],
        action_rule="Replace delivery orders with In's Mercato / Bennet groceries (€10/trip avg).",
    )

    # 6. Dining Out, Pubs & Nightlife (excluding Pellegrini workplace mensa)
    dining_non_mensa = outflow_df[
        (outflow_df["category"].isin(["Dining Out, Bars & Aperitivo", "Entertainment, Nightlife & Hobbies", "Coffee, Snacks & Tabacchi"]))
        & (outflow_df["merchant"] != "Pellegrini Mensa")
    ]
    _add_audit_reactive_leak(
        "dining",
        "Restaurants, Pubs, Tabacchi & Tickets",
        "Dining & Entertainment",
        dining_non_mensa,
        default_ratio=cut_ratios["dining"],
        action_rule="Trim discretionary dining/events while keeping Pellegrini Mensa (€3.05/meal) intact.",
    )

    # 7. PayPal SDD Micro-Charges
    pp_sdd_df = outflow_df[outflow_df["merchant"] == "PayPal SDD"]
    _add_audit_reactive_leak(
        "paypal_sdd",
        "PayPal SDD Micro-Charges",
        "Online Shopping & PayPal",
        pp_sdd_df,
        default_ratio=cut_ratios["paypal_sdd"],
        action_rule="Audit and cancel recurring €2–€12 PayPal direct debits.",
    )

    # 8. BPER €0.40 PayPal SDD Commissions
    pp_fee_df = outflow_df[outflow_df["merchant"] == "Commissione BPER (PayPal SDD)"]
    _add_audit_reactive_leak(
        "bper_fees",
        "BPER €0.40 PayPal SDD Commissions",
        "Bank Fees, Taxes & Bollo",
        pp_fee_df,
        default_ratio=cut_ratios["bper_fees"],
        action_rule="Link PayPal to your BPER debit card (free) instead of IBAN SDD (€0.40 fee per tx).",
        is_fee_channel=True,
    )

    # 9. Also include any OTHER transaction anywhere in the ledger that the user explicitly marked 'Guilty / Bad Purchase'
    covered_ids = set(
        pd.concat([bnpl_df, rev_out_df, ret_df, amz_df, glovo_df, dining_non_mensa, pp_sdd_df, pp_fee_df])["id"].tolist()
    )
    other_guilty_df = outflow_df[(outflow_df["verdict"] == "Guilty / Bad Purchase") & (~outflow_df["id"].isin(covered_ids))]
    if not other_guilty_df.empty:
        _add_audit_reactive_leak(
            "other_guilty",
            "Other Audited Unjustified Spends",
            "Various",
            other_guilty_df,
            default_ratio=1.00,
            action_rule="Transactions explicitly marked Unjustified during your Audit review.",
        )

    leaks_df = pd.DataFrame(leaks)
    if not leaks_df.empty:
        leaks_df = leaks_df.sort_values("Saveable This Period (€)", ascending=False).reset_index(drop=True)

    total_saveable_period = float(leaks_df["Saveable This Period (€)"].sum()) if not leaks_df.empty else 0.0
    total_saveable_monthly = float(leaks_df["Saveable Per Month (€/mo)"].sum()) if not leaks_df.empty else 0.0
    recurring_saveable_monthly = float(leaks_df["rec_save_mo"].sum()) if not leaks_df.empty else 0.0
    onetime_saveable_monthly = float(leaks_df["one_save_mo"].sum()) if not leaks_df.empty else 0.0

    # --- Recurrence-Aware Forward Savings Forecast ---
    # 1. Committed Recurring Essential & Justified Living Baseline (Rent, Utilities, Groceries, Mensa, Remittances)
    # Note: We exclude the investment portion of Fondi and Wise >€300 from living burn so it is counted as Savings/Investments!
    committed_recurring_df = outflow_df[
        (outflow_df["recurrence"] == "Recurring")
        & (outflow_df["verdict"].isin(["Essential Pass", "Justified"]))
    ]
    raw_committed_recurring_total = float(committed_recurring_df["abs_amt"].sum())
    # Subtract the investment portions (Fondi explicit + Wise 12k INR investment portions) from living expense burn
    committed_living_recurring_total = max(
        0.0,
        raw_committed_recurring_total - fondi_explicit_eur - wise_invested_total_eur,
    )
    committed_recurring_monthly = committed_living_recurring_total / n_months

    # 2. Unverified / Suspect Recurring Burn (BNPL, PayPal SDD, unverified recurring habits)
    suspect_recurring_df = outflow_df[
        (outflow_df["recurrence"] == "Recurring")
        & (outflow_df["verdict"].isin(["Pending Review", "Guilty / Bad Purchase"]))
    ]
    suspect_recurring_monthly = float(suspect_recurring_df["abs_amt"].sum()) / n_months

    # 3. Historical One-Time Spikes vs Justified One-Time Buffer
    justified_onetime_df = outflow_df[
        (outflow_df["recurrence"] != "Recurring")
        & (outflow_df["verdict"].isin(["Justified", "Essential Pass"]))
    ]
    suspect_onetime_df = outflow_df[
        (outflow_df["recurrence"] != "Recurring")
        & (outflow_df["verdict"].isin(["Pending Review", "Guilty / Bad Purchase"]))
    ]
    justified_onetime_monthly = float(justified_onetime_df["abs_amt"].sum()) / n_months
    suspect_onetime_monthly = float(suspect_onetime_df["abs_amt"].sum()) / n_months

    # Forecasted steady-state monthly savings (including €100/mo Fondi PAC + Wise 12,000 INR/mo investment + additional cash savings):
    post_cut_recurring_burn = committed_recurring_monthly + max(0.0, suspect_recurring_monthly - recurring_saveable_monthly)
    planned_onetime_allowance = round(max(120.0, justified_onetime_monthly + max(0.0, suspect_onetime_monthly - onetime_saveable_monthly) * 0.5), 0)
    forecast_monthly_savings = round(max(monthly_invested_avg_eur, base_monthly_income - post_cut_recurring_burn - planned_onetime_allowance), 0)
    forecast_annual_savings = round(forecast_monthly_savings * 12.0, 0)

    # --- Audit-Reactive Financial Wisdom Score (0 - 100) ---
    # 1. Fixed Living Overhead Discipline (0-25 pts)
    essential_total = float(outflow_df[essential_mask]["abs_amt"].sum())
    essential_monthly = essential_total / n_months
    overhead_ratio = essential_monthly / max(base_monthly_income, 1.0)
    overhead_pts = max(5.0, min(25.0, 25.0 - max(0.0, overhead_ratio - 0.50) * 45.0))

    # 2. Cashflow Consistency (0-25 pts)
    consistency_pts = max(0.0, 25.0 * (1.0 - (deficit_months / n_months)))

    # 3. Audit & Impulse Discipline (0-25 pts) -> Directly changes as user audits transactions!
    weighted_bad_eur = guilty_eur * 1.0 + pending_eur * 0.65
    bad_share = weighted_bad_eur / max(total_outflow, 1.0)
    hygiene_pts = max(2.0, min(25.0, 25.0 * (1.0 - (bad_share / 0.48))))

    # 4. Net Capital Retention & Audit Engagement (0-25 pts)
    savings_pts = max(0.0, min(20.0, (savings_rate_pct / 20.0) * 20.0))
    audit_engagement_bonus = min(5.0, (audit_completion_pct / 100.0) * 5.0)
    retention_pts = min(25.0, savings_pts + audit_engagement_bonus)

    wisdom_score = int(round(consistency_pts + overhead_pts + hygiene_pts + retention_pts))

    if wisdom_score >= 80:
        rating_label = "Disciplined Allocator"
    elif wisdom_score >= 65:
        rating_label = "Structured & Audit-Verified"
    elif wisdom_score >= 45:
        rating_label = "Strong Core Overhead, Moderate Discretionary Leakage"
    else:
        rating_label = "High Unverified / Discretionary Leakage — Audit & Restructure"

    recommended_essential = round(committed_recurring_monthly if committed_recurring_monthly > 0 else essential_monthly, 0)
    recommended_save_floor = round(max(250.0, base_monthly_income * 0.18), 0)
    recommended_save_optimal = round(
        max(recommended_save_floor, min(base_monthly_income * 0.42, forecast_monthly_savings)),
        0,
    )
    recommended_discretionary_cap = round(max(150.0, base_monthly_income - recommended_essential - recommended_save_floor), 0)

    return {
        "empty": False,
        "n_months": n_months,
        "months": months,
        "deficit_months": deficit_months,
        "total_inflow": round(total_inflow, 2),
        "total_outflow": round(total_outflow, 2),
        "net_retained": round(net_retained, 2),
        "true_wealth_accumulated_eur": round(true_wealth_accumulated_eur, 2),
        "savings_rate_pct": round(savings_rate_pct, 1),
        "cash_only_savings_rate_pct": round(cash_only_savings_rate_pct, 1),
        "wise_gt300_cnt": wise_gt300_cnt,
        "wise_invest_per_tx_eur": round(wise_invest_per_tx_eur, 2),
        "wise_invested_total_inr": round(wise_invested_total_inr, 0),
        "wise_invested_total_eur": round(wise_invested_total_eur, 2),
        "fondi_explicit_eur": round(fondi_explicit_eur, 2),
        "fondi_total_accredited_eur": round(fondi_total_accredited_eur, 2),
        "total_invested_capital_eur": round(total_invested_capital_eur, 2),
        "monthly_invested_avg_eur": round(monthly_invested_avg_eur, 2),
        "base_monthly_income": round(base_monthly_income, 2),
        "avg_monthly_inflow": round(avg_monthly_inflow, 2),
        "avg_monthly_outflow": round(avg_monthly_outflow, 2),
        "essential_monthly": round(essential_monthly, 2),
        "overhead_ratio_pct": round(overhead_ratio * 100.0, 1),
        "recurring_out_total": round(recurring_out_total, 2),
        "onetime_out_total": round(onetime_out_total, 2),
        "recurring_monthly_burn": round(recurring_monthly_burn, 2),
        "onetime_monthly_avg": round(onetime_monthly_avg, 2),
        "committed_recurring_monthly": round(committed_recurring_monthly, 2),
        "suspect_recurring_monthly": round(suspect_recurring_monthly, 2),
        "justified_onetime_monthly": round(justified_onetime_monthly, 2),
        "suspect_onetime_monthly": round(suspect_onetime_monthly, 2),
        "recurring_saveable_monthly": round(recurring_saveable_monthly, 2),
        "onetime_saveable_monthly": round(onetime_saveable_monthly, 2),
        "forecast_monthly_savings": forecast_monthly_savings,
        "forecast_annual_savings": forecast_annual_savings,
        "planned_onetime_allowance": planned_onetime_allowance,
        "wisdom_score": wisdom_score,
        "rating_label": rating_label,
        "score_breakdown": {
            "Essential Overhead Control": f"{overhead_pts:.0f}/25",
            "Cashflow Consistency": f"{consistency_pts:.0f}/25",
            "Audit & Impulse Hygiene": f"{hygiene_pts:.0f}/25",
            "Retention & Audit Progress": f"{retention_pts:.0f}/25",
        },
        "audit_stats": {
            "pending_cnt": pending_cnt,
            "justified_cnt": justified_cnt,
            "guilty_cnt": guilty_cnt,
            "essential_cnt": essential_cnt,
            "pending_eur": round(pending_eur, 2),
            "justified_eur": round(justified_eur, 2),
            "guilty_eur": round(guilty_eur, 2),
            "completion_pct": round(audit_completion_pct, 1),
        },
        "monthly_summary_df": monthly_summary_df,
        "yearly_comparison_df": yearly_comparison_df,
        "leaks_df": leaks_df,
        "total_saveable_period": round(total_saveable_period, 2),
        "total_saveable_monthly": round(total_saveable_monthly, 2),
        "total_saveable_annualized": round(total_saveable_monthly * 12.0, 2),
        "recommended_essential": recommended_essential,
        "recommended_save_floor": recommended_save_floor,
        "recommended_save_optimal": recommended_save_optimal,
        "recommended_discretionary_cap": recommended_discretionary_cap,
        "wise_total": round(float(outflow_df[outflow_df["merchant"] == "Wise Transfer"]["abs_amt"].sum()), 2),
    }
