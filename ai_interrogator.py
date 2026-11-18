import json
import os
import re
from typing import Dict, List, Tuple
import requests


def compute_opportunity_cost(
    amount_eur: float,
    hourly_wage: float = 14.0,
    annual_return: float = 0.08,
) -> Dict[str, float]:
    abs_amt = abs(float(amount_eur))
    wage = max(float(hourly_wage), 1.0)
    hours_worked = abs_amt / wage
    fv_10y = abs_amt * ((1.0 + annual_return) ** 10)
    fv_20y = abs_amt * ((1.0 + annual_return) ** 20)
    annualized_weekly = abs_amt * 52.0
    annualized_10y = annualized_weekly * (((1.0 + annual_return) ** 10 - 1.0) / annual_return)
    return {
        "amount": round(abs_amt, 2),
        "hours_worked": round(hours_worked, 1),
        "fv_10y": round(fv_10y, 2),
        "fv_20y": round(fv_20y, 2),
        "if_weekly_10y": round(annualized_10y, 2),
    }


def _build_interrogator_system_prompt(strictness: str, hourly_wage: float, monthly_savings_goal: float) -> str:
    return f"""You are a minimalist, sharp, and objective personal finance auditor.
Tone: {strictness}. Zero emojis, zero exclamation points, zero theatrical roleplay, zero filler.
User net hourly wage: EUR {hourly_wage:.2f}/h. Monthly savings target: EUR {monthly_savings_goal:.2f}.

Guidelines:
1. State the exact labor cost (hours worked) and 10-year compounded cost (at 8%) concisely.
2. Reject vague rationalizations ("convenience", "on sale", "felt like it", "tired").
3. Ask one direct, analytical question testing necessity, alternatives, AND whether this is a one-time expense or a recurring habit/commitment.
4. Grant 'Justified' only when the user demonstrates clear utility, necessity, or a planned allocation within budget. Otherwise assign 'Pending Review' or 'Guilty / Bad Purchase'.
5. Infer whether the expense is 'One-Time' or 'Recurring' from the merchant and the user's answer.
6. Keep your response under 75 words, plain text, no bullet lists or bolding excess. End with a JSON block inside ```json ... ```:
   {{
     "verdict_recommendation": "Pending Review" | "Justified" | "Guilty / Bad Purchase",
     "recurrence_recommendation": "One-Time" | "Recurring",
     "regret_score": <integer 0 to 100>,
     "one_line_roast": "<concise 1-line audit note, max 90 chars, no emojis>"
   }}
"""


def _extract_json_verdict(text: str, default_recurrence: str = "One-Time") -> Tuple[str, Dict[str, object]]:
    meta: Dict[str, object] = {
        "verdict_recommendation": "Pending Review",
        "recurrence_recommendation": default_recurrence,
        "regret_score": 65,
        "one_line_roast": "",
    }
    pattern = r"```json\s*(\{.*?\})\s*```"
    match = re.search(pattern, text, flags=re.DOTALL)
    clean_text = text
    if match:
        try:
            parsed = json.loads(match.group(1))
            meta.update(parsed)
            clean_text = text[: match.start()].strip()
        except Exception:
            pass
    if meta.get("recurrence_recommendation") not in ("One-Time", "Recurring"):
        meta["recurrence_recommendation"] = default_recurrence
    if not meta.get("one_line_roast"):
        first_line = clean_text.split("\n")[0].strip()
        meta["one_line_roast"] = first_line[:110]
    return clean_text, meta


def _heuristic_interrogator(
    merchant: str,
    amount: float,
    category: str,
    conversation: List[Dict[str, str]],
    opp: Dict[str, float],
    current_recurrence: str = "One-Time",
) -> Tuple[str, Dict[str, object]]:
    abs_amt = opp["amount"]
    hrs = opp["hours_worked"]
    fv10 = opp["fv_10y"]
    fv20 = opp["fv_20y"]

    user_msgs = [m["content"] for m in conversation if m["role"] == "user"]
    turn_count = len(user_msgs)

    if turn_count == 0:
        cat_lower = category.lower()
        if "delivery" in cat_lower or any(k in merchant.upper() for k in ("GLOVO", "DELIVEROO", "JUST EAT", "MCDONALD", "POKE")):
            msg = (
                f"€{abs_amt:.2f} at {merchant} represents {hrs} hours of net labor and €{fv10:.2f} in 10-year compounded capital. "
                f"Repeated weekly, this single habit drains €{opp['if_weekly_10y']:,.0f} over a decade.\n\n"
                f"Is this a one-time convenience order or a recurring delivery habit, and what prevented you from preparing food at home?"
            )
            score = 82
            note = f"Delivery convenience premium ({hrs}h labor)."
        elif "online shopping" in cat_lower or "paypal" in cat_lower:
            msg = (
                f"€{abs_amt:.2f} via {merchant} equals {hrs} hours of work (€{fv10:.2f} over 10 years at 8%).\n\n"
                f"Is this a one-time online purchase or a recurring PayPal installment/charge, and was the item planned at least 48 hours in advance?"
            )
            score = 76
            note = f"Online shopping / PayPal spend ({hrs}h labor)."
        elif "shopping" in cat_lower or any(k in merchant.upper() for k in ("AMAZON", "ZARA", "ZALANDO", "SHEIN", "TEMU", "APPLE")):
            msg = (
                f"€{abs_amt:.2f} at {merchant} equals {hrs} hours of work (€{fv20:.2f} over 20 years at 8%).\n\n"
                f"Is this a one-time purchase or a recurring expense, and was it on a written list at least 48 hours prior?"
            )
            score = 75
            note = f"Unverified retail spend ({hrs}h labor)."
        elif "coffee" in cat_lower or "dining" in cat_lower:
            msg = (
                f"€{abs_amt:.2f} at {merchant} ({hrs} hours of work). At a weekly pace, this represents €{opp['if_weekly_10y']:,.0f} in 10-year opportunity cost.\n\n"
                f"Was this a one-time social occasion or a recurring routine expense?"
            )
            score = 60
            note = f"Discretionary dining ({hrs}h labor)."
        else:
            msg = (
                f"€{abs_amt:.2f} at {merchant} ({category}) required {hrs} hours of labor (€{fv10:.2f} 10-year opportunity cost).\n\n"
                f"State the specific utility of this transaction and specify whether it is a one-time expense or a recurring commitment."
            )
            score = 65
            note = f"Pending audit ({hrs}h labor)."

        return msg, {
            "verdict_recommendation": "Pending Review",
            "recurrence_recommendation": current_recurrence,
            "regret_score": score,
            "one_line_roast": note,
        }

    last_excuse = user_msgs[-1].strip()
    lower_excuse = last_excuse.lower()

    # Detect explicit recurrence cues in user's response
    rec_rec = current_recurrence
    if any(w in lower_excuse for w in ("one time", "one-time", "once", "single", "una tantum", "singolo", "1 time")):
        rec_rec = "One-Time"
    elif any(w in lower_excuse for w in ("recurring", "monthly", "weekly", "subscription", "habit", "ricorrente", "mensile", "abbonamento", "every month")):
        rec_rec = "Recurring"

    weak_words = ["tired", "lazy", "bored", "sale", "discount", "wanted", "treat", "stressed", "idk", "don't know", "stanco", "sconto", "voglia", "noia"]
    honest_guilt_words = ["guilty", "bad", "mistake", "impulse", "regret", "colpevole", "errore", "impulso", "unjustified"]
    strong_words = ["work", "client", "essential", "broken", "replaced", "planned", "budgeted", "gift", "medical", "family", "needed", "lavoro", "rotto", "pianificato"]

    if any(w in lower_excuse for w in honest_guilt_words):
        reply = (
            f"Logged as Unjustified ({rec_rec}). €{abs_amt:.2f} ({hrs} hours of labor) recorded against discretionary leakage. "
            f"Consider transferring an equivalent amount to savings to offset the drawdown."
        )
        return reply, {
            "verdict_recommendation": "Guilty / Bad Purchase",
            "recurrence_recommendation": rec_rec,
            "regret_score": 88,
            "one_line_roast": f"Acknowledged impulse ({rec_rec}): '{last_excuse[:45]}'",
        }

    if any(w in lower_excuse for w in weak_words) or len(last_excuse) < 18:
        if turn_count == 1:
            reply = (
                f"\"{last_excuse}\" is a rationalization, not a justification. "
                f"A discount or fatigue does not change the fact that €{abs_amt:.2f} cost {hrs} hours of your time. "
                f"Provide an objective reason why this expense was necessary (and whether it is one-time or recurring), or mark it Unjustified."
            )
            return reply, {
                "verdict_recommendation": "Pending Review",
                "recurrence_recommendation": rec_rec,
                "regret_score": 80,
                "one_line_roast": f"Insufficient rationale ({rec_rec}): '{last_excuse[:40]}'",
            }
        else:
            reply = (
                f"Explanation insufficient after {turn_count} reviews. "
                f"€{abs_amt:.2f} at {merchant} has been classified as Unjustified ({rec_rec})."
            )
            return reply, {
                "verdict_recommendation": "Guilty / Bad Purchase",
                "recurrence_recommendation": rec_rec,
                "regret_score": 85,
                "one_line_roast": f"Unjustified spend ({rec_rec}): '{last_excuse[:40]}'",
            }

    if any(w in lower_excuse for w in strong_words) or len(last_excuse) >= 35:
        reply = (
            f"Accepted. Your rationale (\"{last_excuse}\") indicates planned utility ({rec_rec}). "
            f"Transaction marked as Justified."
        )
        return reply, {
            "verdict_recommendation": "Justified",
            "recurrence_recommendation": rec_rec,
            "regret_score": 15,
            "one_line_roast": f"Verified ({rec_rec}): {last_excuse[:55]}",
        }

    reply = (
        f"Your note (\"{last_excuse}\") remains ambiguous. Given a cost of {hrs} hours of work (€{fv10:.2f} over 10 years), "
        f"confirm if this is a one-time or recurring expense and whether you would make this purchase again today."
    )
    return reply, {
        "verdict_recommendation": "Pending Review",
        "recurrence_recommendation": rec_rec,
        "regret_score": 65,
        "one_line_roast": f"Under review ({rec_rec}): '{last_excuse[:40]}'",
    }


def interrogate_transaction(
    merchant: str,
    description: str,
    amount: float,
    category: str,
    tx_date: str,
    conversation: List[Dict[str, str]],
    provider: str = "gemini",
    model: str = "gemini-2.5-flash",
    api_key: str = "",
    strictness: str = "Direct & Analytical",
    hourly_wage: float = 14.0,
    monthly_savings_goal: float = 600.0,
    recurrence: str = "One-Time",
) -> Tuple[str, Dict[str, object]]:
    opp = compute_opportunity_cost(amount, hourly_wage=hourly_wage)
    sys_prompt = _build_interrogator_system_prompt(strictness, hourly_wage, monthly_savings_goal)

    tx_context = (
        f"Transaction:\n"
        f"Date: {tx_date}\n"
        f"Merchant: {merchant} ({description})\n"
        f"Category: {category}\n"
        f"Current Frequency Tag: {recurrence}\n"
        f"Amount: EUR {opp['amount']:.2f}\n"
        f"Labor equivalent (at EUR {hourly_wage:.2f}/h): {opp['hours_worked']} hours\n"
        f"10Y compounded value (8%): EUR {opp['fv_10y']:.2f}\n"
        f"20Y compounded value (8%): EUR {opp['fv_20y']:.2f}\n"
    )

    effective_key = api_key.strip()
    if not effective_key:
        if provider == "gemini":
            effective_key = os.environ.get("GEMINI_API_KEY", "") or os.environ.get("GOOGLE_API_KEY", "")
        elif provider == "openai":
            effective_key = os.environ.get("OPENAI_API_KEY", "")

    if not effective_key and provider in ("gemini", "openai"):
        return _heuristic_interrogator(merchant, amount, category, conversation, opp, current_recurrence=recurrence)

    try:
        if provider == "gemini":
            from google import genai
            from google.genai import types

            client = genai.Client(api_key=effective_key)
            prompt_parts = [tx_context]
            if not conversation:
                prompt_parts.append(
                    "Initiate the audit of this expense. State the labor and 10-year cost concisely and ask one direct question including whether this is a one-time or recurring expense."
                )
            else:
                for msg in conversation:
                    role_label = "AUDITOR" if msg["role"] == "assistant" else "USER"
                    prompt_parts.append(f"{role_label}: {msg['content']}")
                prompt_parts.append("Evaluate the user's latest explanation and append the JSON verdict block.")

            resp = client.models.generate_content(
                model=model or "gemini-2.5-flash",
                contents="\n\n".join(prompt_parts),
                config=types.GenerateContentConfig(
                    system_instruction=sys_prompt,
                    temperature=0.4,
                ),
            )
            if resp and resp.text:
                return _extract_json_verdict(resp.text, default_recurrence=recurrence)

        elif provider == "openai":
            from openai import OpenAI

            client = OpenAI(api_key=effective_key)
            messages = [{"role": "system", "content": sys_prompt + "\n\n" + tx_context}]
            if not conversation:
                messages.append(
                    {
                        "role": "user",
                        "content": "Audit this transaction, ask for my justification and whether it is one-time or recurring.",
                    }
                )
            else:
                messages.extend(conversation)

            resp = client.chat.completions.create(
                model=model or "gpt-4o-mini",
                messages=messages,
                temperature=0.4,
            )
            text = resp.choices[0].message.content or ""
            if text:
                return _extract_json_verdict(text, default_recurrence=recurrence)

        elif provider == "ollama":
            messages = [{"role": "system", "content": sys_prompt + "\n\n" + tx_context}]
            if not conversation:
                messages.append({"role": "user", "content": "Audit this purchase."})
            else:
                messages.extend(conversation)
            r = requests.post(
                "http://localhost:11434/api/chat",
                json={"model": model or "llama3.1", "messages": messages, "stream": False},
                timeout=20,
            )
            if r.status_code == 200:
                text = r.json().get("message", {}).get("content", "")
                if text:
                    return _extract_json_verdict(text, default_recurrence=recurrence)

    except Exception:
        pass

    return _heuristic_interrogator(merchant, amount, category, conversation, opp, current_recurrence=recurrence)
