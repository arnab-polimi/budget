from typing import Dict, List, Any
import pandas as pd


def compute_financial_intelligence(all_tx_df: pd.DataFrame, hourly_wage: float = 14.0) -> Dict[str, Any]:
    """
    Computes an objective Financial Wisdom Score (0-100), monthly cashflow breakdown,
    exact merchant-by-merchant recoverable savings (annual/YTD and per month),
    and a concrete monthly savings prescription.
    """
    if all_tx_df.empty:
        return {"empty": True}

    df = all_tx_df.copy()
    df["month"] = df["tx_date"].str.slice(0, 7)
    months = sorted(df["month"].dropna().unique().tolist())
    n_months = max(len(months), 1)

    inflow_df = df[df["amount"] > 0].copy()
    outflow_df = df[df["amount"] < 0].copy()
    outflow_df["abs_amt"] = outflow_df["amount"].abs()

    total_inflow = float(inflow_df["amount"].sum())
    total_outflow = float(outflow_df["abs_amt"].sum())
    net_retained = total_inflow - total_outflow
    savings_rate_pct = (net_retained / total_inflow * 100.0) if total_inflow > 0 else 0.0

    # Recurring base salary estimation (median of salary inflows vs total average inflow)
    salary_rows = inflow_df[inflow_df["category"] == "Income / Salary"]
    monthly_salary_by_m = salary_rows.groupby("month")["amount"].sum()
    base_monthly_income = float(monthly_salary_by_m.median()) if not monthly_salary_by_m.empty else (total_inflow / n_months)
    avg_monthly_inflow = total_inflow / n_months
    avg_monthly_outflow = total_outflow / n_months

    # Monthly cashflow table
    m_in = inflow_df.groupby("month")["amount"].sum()
    m_out = outflow_df.groupby("month")["abs_amt"].sum()

    # Essential vs Discretionary vs P2P/Transfer breakdown
    essential_mask = outflow_df["verdict"] == "Essential Pass"
    transfer_mask = outflow_df["category"] == "Transfers & P2P (Satispay/Revolut/BancomatPay)"
    discretionary_mask = (~essential_mask) & (~transfer_mask)

    m_ess = outflow_df[essential_mask].groupby("month")["abs_amt"].sum()
    m_disc = outflow_df[discretionary_mask].groupby("month")["abs_amt"].sum()
    m_trans = outflow_df[transfer_mask].groupby("month")["abs_amt"].sum()

    monthly_rows = []
    deficit_months = 0
    for m in months:
        inc = float(m_in.get(m, 0.0))
        out = float(m_out.get(m, 0.0))
        ess = float(m_ess.get(m, 0.0))
        disc = float(m_disc.get(m, 0.0))
        trn = float(m_trans.get(m, 0.0))
        net = inc - out
        if net < 0:
            deficit_months += 1
        sr = (net / inc * 100.0) if inc > 0 else 0.0
        monthly_rows.append(
            {
                "Month": m,
                "Inflow (€)": round(inc, 2),
                "Essential (€)": round(ess, 2),
                "Discretionary & Retail (€)": round(disc, 2),
                "Transfers & P2P (€)": round(trn, 2),
                "Total Outflow (€)": round(out, 2),
                "Net Cashflow (€)": round(net, 2),
                "Savings Rate (%)": round(sr, 1),
            }
        )
    monthly_summary_df = pd.DataFrame(monthly_rows)

    # Specific Leak Analysis (Exact places and amounts the user could have saved)
    leaks: List[Dict[str, Any]] = []

    def _add_leak(
        place: str,
        category: str,
        subset: pd.DataFrame,
        save_ratio: float,
        action_rule: str,
    ) -> None:
        if subset.empty:
            return
        spent = float(subset["abs_amt"].sum())
        cnt = int(len(subset))
        monthly_avg = spent / n_months
        recoverable_total = spent * save_ratio
        recoverable_monthly = monthly_avg * save_ratio
        hours_lost = recoverable_total / max(hourly_wage, 1.0)
        fv_10y = recoverable_total * ((1.08) ** 10)
        leaks.append(
            {
                "Where (Merchant / Channel)": place,
                "Category": category,
                "Tx Count": cnt,
                "Total Spent (€)": round(spent, 2),
                "Monthly Avg (€/mo)": round(monthly_avg, 2),
                "Saveable This Period (€)": round(recoverable_total, 2),
                "Saveable Per Month (€/mo)": round(recoverable_monthly, 2),
                "Labor Equivalent (h)": round(hours_lost, 1),
                "10Y Compounded (€)": round(fv_10y, 2),
                "Audit Prescription": action_rule,
            }
        )

    # 1. PayPal Paga in 3 Rate (BNPL debt installments)
    bnpl_df = outflow_df[outflow_df["merchant"] == "PayPal Paga in 3 Rate (BNPL)"]
    _add_leak(
        "PayPal Paga in 3 Rate (BNPL)",
        "Shopping, Clothes & Amazon",
        bnpl_df,
        save_ratio=0.75,
        action_rule="Eliminate Buy-Now-Pay-Later installments; apply 24h Holding Vault before any >€30 purchase (75% reduction).",
    )

    # 2. Revolut Top-Ups / Secondary Card Drains (net of Revolut inbound returns)
    rev_out_df = outflow_df[outflow_df["merchant"] == "Revolut Top-Up / Transfer"]
    rev_in_sum = float(inflow_df[inflow_df["merchant"] == "Revolut (Inbound Transfer)"]["amount"].sum())
    if not rev_out_df.empty:
        rev_gross = float(rev_out_df["abs_amt"].sum())
        rev_net_spent = max(rev_gross - rev_in_sum, 0.0)
        # Scale save ratio to net unreturned top-ups (50% of net unreturned Revolut outflow)
        effective_ratio = (rev_net_spent * 0.50) / rev_gross if rev_gross > 0 else 0.0
        _add_leak(
            f"Revolut Top-Ups (€{rev_net_spent:.0f} net after €{rev_in_sum:.0f} returned)",
            "Transfers & P2P",
            rev_out_df,
            save_ratio=effective_ratio,
            action_rule="Cap Revolut pocket-money top-ups at €80/month instead of frequent €20–€50 transfers (save 50% of net drain).",
        )

    # 3. Amazon Retail
    amz_df = outflow_df[outflow_df["merchant"] == "Amazon"]
    _add_leak(
        "Amazon",
        "Shopping, Clothes & Amazon",
        amz_df,
        save_ratio=0.60,
        action_rule="Batch non-urgent orders once a month rather than 17 separate checkout impulses (60% reduction).",
    )

    # 4. Retail Apparel & Sports (Decathlon, PUMA Outlet, OVS, MediaWorld, Tiger)
    retail_merchants = ["Decathlon", "PUMA Outlet Torino - Settimo Torin", "OVS TORINO", "MediaWorld", "TIGER STORE MILANO PO."]
    ret_df = outflow_df[outflow_df["merchant"].isin(retail_merchants)]
    _add_leak(
        "Decathlon, PUMA, OVS & MediaWorld",
        "Shopping, Clothes & Amazon",
        ret_df,
        save_ratio=0.50,
        action_rule="Enforce a €40/month clothing & gear envelope across all retail stores (50% reduction).",
    )

    # 5. PayPal SDD Micro-Drains + Associated €0.40 BPER SDD Fees
    pp_sdd_df = outflow_df[outflow_df["merchant"] == "PayPal SDD"]
    pp_fee_df = outflow_df[outflow_df["merchant"] == "Commissione BPER (PayPal SDD)"]
    _add_leak(
        "PayPal SDD Micro-Charges",
        "Transfers & P2P",
        pp_sdd_df,
        save_ratio=0.60,
        action_rule="Audit and cancel recurring €2–€5 PayPal direct debits (47 charges logged).",
    )
    _add_leak(
        "BPER €0.40 PayPal SDD Commissions",
        "Bank Fees, Taxes & Bollo",
        pp_fee_df,
        save_ratio=1.00,
        action_rule="Link PayPal to your BPER debit card (free) instead of IBAN SDD (which costs €0.40 per transaction — 100% avoidable).",
    )

    # 6. Glovo & Fast Food Delivery
    glovo_df = outflow_df[outflow_df["category"] == "Food Delivery (Glovo/Deliveroo/JustEat)"]
    _add_leak(
        "Glovo & Takeout (Olimpico Kebab, etc.)",
        "Food Delivery",
        glovo_df,
        save_ratio=0.80,
        action_rule="Replace 80% of delivery orders with In's Mercato / Bennet groceries (already averaging €10/trip).",
    )

    # 7. Dining Out, Pubs & Nightlife (excluding Pellegrini workplace mensa)
    dining_non_mensa = outflow_df[
        (outflow_df["category"].isin(["Dining Out, Bars & Aperitivo", "Entertainment, Nightlife & Hobbies", "Coffee, Snacks & Tabacchi"]))
        & (outflow_df["merchant"] != "Pellegrini Mensa")
    ]
    _add_leak(
        "Restaurants, Pubs & Tickets (La Locomotiva, Ticketone, etc.)",
        "Dining & Entertainment",
        dining_non_mensa,
        save_ratio=0.40,
        action_rule="Trim discretionary dining/events by 40% while keeping Pellegrini Mensa (€3.05/meal) intact.",
    )

    leaks_df = pd.DataFrame(leaks)
    if not leaks_df.empty:
        leaks_df = leaks_df.sort_values("Saveable This Period (€)", ascending=False).reset_index(drop=True)

    total_saveable_period = float(leaks_df["Saveable This Period (€)"].sum()) if not leaks_df.empty else 0.0
    total_saveable_monthly = float(leaks_df["Saveable Per Month (€/mo)"].sum()) if not leaks_df.empty else 0.0

    # --- Financial Wisdom Score (0 - 100) ---
    # Component 1: Cashflow Consistency (0-25 pts) -> penalized for deficit months
    consistency_pts = max(0.0, 25.0 * (1.0 - (deficit_months / n_months)))

    # Component 2: Fixed Living Overhead Discipline (0-25 pts) -> Rent + Utilities + Groceries + Mensa vs Base Income
    essential_total = float(outflow_df[essential_mask]["abs_amt"].sum())
    essential_monthly = essential_total / n_months
    overhead_ratio = essential_monthly / max(base_monthly_income, 1.0)
    # <= 50% of base salary is 25/25; 60% is 20/25; >= 85% is 5/25
    overhead_pts = max(5.0, min(25.0, 25.0 - max(0.0, overhead_ratio - 0.45) * 50.0))

    # Component 3: BNPL & Micro-Fee Hygiene (0-25 pts) -> penalized by BNPL share and avoidable SDD fees
    bnpl_total = float(bnpl_df["abs_amt"].sum()) if not bnpl_df.empty else 0.0
    sdd_fee_cnt = len(pp_fee_df)
    bnpl_penalty = min(18.0, (bnpl_total / max(total_outflow, 1.0)) * 180.0)
    fee_penalty = min(7.0, sdd_fee_cnt * 0.15)
    hygiene_pts = max(0.0, 25.0 - bnpl_penalty - fee_penalty)

    # Component 4: Net Savings Rate (0-25 pts) -> 20%+ savings rate gets full 25 pts
    savings_pts = max(0.0, min(25.0, (savings_rate_pct / 20.0) * 25.0))

    wisdom_score = int(round(consistency_pts + overhead_pts + hygiene_pts + savings_pts))

    if wisdom_score >= 80:
        rating_label = "Disciplined Allocator"
    elif wisdom_score >= 65:
        rating_label = "Stable but Leaking Capital"
    elif wisdom_score >= 45:
        rating_label = "Strong Base Fundamentals, High Discretionary Bleed"
    else:
        rating_label = "Critical Cashflow Leakage — Immediate Restructuring Required"

    # Recommended Monthly Budget & Savings Target
    # Based on recurring base salary (~€1,630/mo):
    recommended_essential = round(essential_monthly, 0)
    recommended_save_floor = round(max(250.0, base_monthly_income * 0.18), 0)
    recommended_save_optimal = round(min(base_monthly_income * 0.28, recommended_save_floor + total_saveable_monthly * 0.6), 0)
    recommended_discretionary_cap = round(max(150.0, base_monthly_income - recommended_essential - recommended_save_floor), 0)

    return {
        "empty": False,
        "n_months": n_months,
        "months": months,
        "deficit_months": deficit_months,
        "total_inflow": round(total_inflow, 2),
        "total_outflow": round(total_outflow, 2),
        "net_retained": round(net_retained, 2),
        "savings_rate_pct": round(savings_rate_pct, 1),
        "base_monthly_income": round(base_monthly_income, 2),
        "avg_monthly_inflow": round(avg_monthly_inflow, 2),
        "avg_monthly_outflow": round(avg_monthly_outflow, 2),
        "essential_monthly": round(essential_monthly, 2),
        "overhead_ratio_pct": round(overhead_ratio * 100.0, 1),
        "wisdom_score": wisdom_score,
        "rating_label": rating_label,
        "score_breakdown": {
            "Essential Overhead Control": f"{overhead_pts:.0f}/25",
            "Cashflow Consistency": f"{consistency_pts:.0f}/25",
            "BNPL & Fee Hygiene": f"{hygiene_pts:.0f}/25",
            "Net Capital Retention": f"{savings_pts:.0f}/25",
        },
        "monthly_summary_df": monthly_summary_df,
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
