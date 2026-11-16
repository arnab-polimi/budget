from typing import Dict, List, Any, Optional
import pandas as pd


def compute_financial_intelligence(
    all_tx_df: pd.DataFrame,
    hourly_wage: float = 14.0,
    custom_cut_ratios: Optional[Dict[str, float]] = None,
    include_justified_in_leaks: bool = False,
) -> Dict[str, Any]:
    """
    Computes an audit-reactive Financial Wisdom Score (0-100), monthly cashflow breakdown,
    exact merchant-by-merchant recoverable savings (annual/YTD and per month),
    and a concrete monthly savings prescription.

    Dynamically reacts to:
    1. Every transaction audited by the user (marking a transaction 'Justified' or 'Essential Pass'
       removes it from the leak pool unless `include_justified_in_leaks` is True; marking it
       'Guilty / Bad Purchase' weights it at 100% recoverable unless overridden by sliders).
    2. Interactive target reduction sliders (`custom_cut_ratios`) in the Advisory tab.
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

    # Specific Leak Analysis (Reactive to Audit Verdicts + Interactive Sliders!)
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
            # Confirmed guilty spends are 100% waste (or scaled by slider if user wants), pending spends use slider ratio
            effective_pending = max(0.0, pending_amt - net_offset_eur)
            recoverable_total = (guilty_amt * max(default_ratio, 0.90)) + (effective_pending * default_ratio)

        recoverable_monthly = recoverable_total / n_months
        hours_lost = recoverable_total / max(hourly_wage, 1.0)
        fv_10y = recoverable_total * ((1.08) ** 10)

        leaks.append(
            {
                "key": key,
                "Where (Merchant / Channel)": place,
                "Category": category,
                "Tx Count": int(len(subset)),
                "Total Spent (€)": round(total_channel_spent, 2),
                "Cleared / Justified (€)": round(cleared_amt, 2),
                "Unjustified / Pending (€)": round(guilty_amt + pending_amt, 2),
                "Target Cut (%)": int(round(default_ratio * 100)),
                "Saveable This Period (€)": round(recoverable_total, 2),
                "Saveable Per Month (€/mo)": round(recoverable_monthly, 2),
                "Labor Equivalent (h)": round(hours_lost, 1),
                "10Y Compounded (€)": round(fv_10y, 2),
                "Audit Prescription": action_rule,
            }
        )

    # 1. PayPal Paga in 3 Rate (BNPL)
    bnpl_df = outflow_df[outflow_df["merchant"] == "PayPal Paga in 3 Rate (BNPL)"]
    _add_audit_reactive_leak(
        "bnpl",
        "PayPal Paga in 3 Rate (BNPL)",
        "Shopping, Clothes & Amazon",
        bnpl_df,
        default_ratio=cut_ratios["bnpl"],
        action_rule="Eliminate BNPL installments; use 24h Holding Vault before any >€30 purchase.",
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

    # 3. Retail Apparel & Sports (Decathlon, PUMA Outlet, OVS, MediaWorld, Tiger)
    retail_merchants = ["Decathlon", "PUMA Outlet Torino - Settimo Torin", "OVS TORINO", "MediaWorld", "TIGER STORE MILANO PO."]
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
        "Restaurants, Pubs & Tickets (La Locomotiva, Ticketone)",
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
        "Transfers & P2P",
        pp_sdd_df,
        default_ratio=cut_ratios["paypal_sdd"],
        action_rule="Audit and cancel recurring €2–€5 PayPal direct debits.",
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

    # --- Audit-Reactive Financial Wisdom Score (0 - 100) ---
    # 1. Fixed Living Overhead Discipline (0-25 pts)
    essential_total = float(outflow_df[essential_mask]["abs_amt"].sum())
    essential_monthly = essential_total / n_months
    overhead_ratio = essential_monthly / max(base_monthly_income, 1.0)
    overhead_pts = max(5.0, min(25.0, 25.0 - max(0.0, overhead_ratio - 0.50) * 45.0))

    # 2. Cashflow Consistency (0-25 pts)
    consistency_pts = max(0.0, 25.0 * (1.0 - (deficit_months / n_months)))

    # 3. Audit & Impulse Discipline (0-25 pts) -> Directly changes as user audits transactions!
    # Unreviewed ('Pending Review') weighs 0.65 as suspect; 'Guilty' weighs 1.0; 'Justified' weighs 0.0!
    weighted_bad_eur = guilty_eur * 1.0 + pending_eur * 0.65
    bad_share = weighted_bad_eur / max(total_outflow, 1.0)
    # If bad_share == 0 -> 25/25; if bad_share >= 0.45 -> 2/25
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

    recommended_essential = round(essential_monthly, 0)
    recommended_save_floor = round(max(250.0, base_monthly_income * 0.18), 0)
    recommended_save_optimal = round(min(base_monthly_income * 0.35, recommended_save_floor + total_saveable_monthly * 0.65), 0)
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
