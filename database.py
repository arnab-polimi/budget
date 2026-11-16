import os
import sqlite3
import subprocess
import hashlib
import base64
import json
from datetime import datetime
from typing import Dict, List, Optional, Tuple, Any
import pandas as pd
import requests

ROOT_DIR = os.path.dirname(os.path.abspath(__file__))
DB_DIR = os.path.join(ROOT_DIR, "data")
DB_PATH = os.path.join(DB_DIR, "budget_2027.db")

DEFAULT_CATEGORIES = [
    ("Groceries & Supermarket", "Essential", 300.0, ""),
    ("Rent / Mortgage & Utilities", "Essential", 750.0, ""),
    ("Transport, Fuel & Transit", "Essential", 150.0, ""),
    ("Health, Pharmacy & Medical", "Essential", 80.0, ""),
    ("Dining Out, Bars & Aperitivo", "Discretionary", 120.0, ""),
    ("Food Delivery (Glovo/Deliveroo/JustEat)", "Impulse", 40.0, ""),
    ("Shopping, Clothes & Amazon", "Impulse", 100.0, ""),
    ("Subscriptions & Digital Services", "Discretionary", 45.0, ""),
    ("Coffee, Snacks & Tabacchi", "Impulse", 35.0, ""),
    ("Entertainment, Nightlife & Hobbies", "Discretionary", 80.0, ""),
    ("Travel & Vacations", "Discretionary", 150.0, ""),
    ("Transfers & P2P (Satispay/Revolut/BancomatPay)", "Discretionary", 100.0, ""),
    ("Bank Fees, Taxes & Bollo", "Essential", 20.0, ""),
    ("Savings & Investments", "Savings", 500.0, ""),
    ("Income / Salary", "Income", 0.0, ""),
    ("Other / Uncategorized", "Impulse", 50.0, ""),
]

DEFAULT_SETTINGS = {
    "monthly_income_target": "2200.0",
    "hourly_wage": "14.0",
    "monthly_savings_goal": "600.0",
    "ai_provider": "gemini",
    "ai_model": "gemini-2.5-flash",
    "interrogator_strictness": "Direct & Analytical",
    "suspect_threshold_eur": "15.0",
    "expected_return_rate": "0.08",
}


def get_connection() -> sqlite3.Connection:
    os.makedirs(DB_DIR, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    conn = get_connection()
    cur = conn.cursor()

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS transactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tx_hash TEXT UNIQUE,
            tx_date TEXT NOT NULL,
            valuta_date TEXT,
            description TEXT NOT NULL,
            merchant TEXT,
            amount REAL NOT NULL,
            category TEXT NOT NULL,
            tx_type TEXT NOT NULL,
            source TEXT NOT NULL,
            verdict TEXT DEFAULT 'Pending Review',
            regret_score INTEGER DEFAULT 0,
            user_excuse TEXT DEFAULT '',
            ai_roast TEXT DEFAULT '',
            interrogation_history TEXT DEFAULT '[]',
            created_at TEXT NOT NULL
        )
        """
    )

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS categories (
            name TEXT PRIMARY KEY,
            tier TEXT NOT NULL,
            monthly_limit REAL NOT NULL,
            icon TEXT DEFAULT ''
        )
        """
    )

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS wishlist_vault (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            item_name TEXT NOT NULL,
            price REAL NOT NULL,
            category TEXT NOT NULL,
            urge_reason TEXT,
            ai_initial_warning TEXT,
            created_at TEXT NOT NULL,
            unlock_at TEXT NOT NULL,
            status TEXT DEFAULT 'Locked'
        )
        """
    )

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        )
        """
    )

    cur.execute("SELECT COUNT(*) as cnt FROM categories")
    if cur.fetchone()["cnt"] == 0:
        cur.executemany(
            "INSERT OR IGNORE INTO categories (name, tier, monthly_limit, icon) VALUES (?, ?, ?, ?)",
            DEFAULT_CATEGORIES,
        )
    else:
        # Clean out legacy emojis from existing DB rows if present
        cur.execute("UPDATE categories SET icon = ''")
        cur.execute("UPDATE categories SET tier = 'Discretionary' WHERE tier = 'Want'")
        cur.execute("UPDATE categories SET tier = 'Impulse' WHERE tier = 'Impulse / Suspect'")

    for k, v in DEFAULT_SETTINGS.items():
        cur.execute("INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)", (k, str(v)))

    conn.commit()
    conn.close()


def compute_tx_hash(tx_date: str, amount: float, description: str) -> str:
    clean_desc = " ".join(str(description).strip().upper().split())
    raw = f"{tx_date}|{amount:.2f}|{clean_desc}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]


def get_setting(key: str, default: str = "") -> str:
    conn = get_connection()
    row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    conn.close()
    return row["value"] if row else default


def set_setting(key: str, value: str) -> None:
    conn = get_connection()
    conn.execute(
        "INSERT INTO settings (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, str(value)),
    )
    conn.commit()
    conn.close()


def get_all_settings() -> Dict[str, str]:
    conn = get_connection()
    rows = conn.execute("SELECT key, value FROM settings").fetchall()
    conn.close()
    res = dict(DEFAULT_SETTINGS)
    for r in rows:
        res[r["key"]] = r["value"]
    return res


def get_categories_df() -> pd.DataFrame:
    conn = get_connection()
    df = pd.read_sql_query("SELECT name, tier, monthly_limit FROM categories ORDER BY tier, name", conn)
    conn.close()
    return df


def update_category_budget(name: str, tier: str, monthly_limit: float) -> None:
    conn = get_connection()
    conn.execute(
        "UPDATE categories SET tier = ?, monthly_limit = ? WHERE name = ?",
        (tier, float(monthly_limit), name),
    )
    conn.commit()
    conn.close()


def add_transaction(
    tx_date: str,
    description: str,
    amount: float,
    category: str,
    source: str = "Manual",
    verdict: str = "Pending Review",
    regret_score: int = 0,
    user_excuse: str = "",
    ai_roast: str = "",
    interrogation_history: Optional[List[Dict[str, str]]] = None,
    valuta_date: Optional[str] = None,
    merchant: str = "",
    allow_duplicate_manual: bool = True,
) -> Tuple[bool, Optional[int]]:
    conn = get_connection()
    cur = conn.cursor()

    tx_type = "Income" if amount > 0 else "Expense"
    now_iso = datetime.now().isoformat(timespec="seconds")
    if allow_duplicate_manual and source == "Manual":
        tx_hash = hashlib.sha256(f"{tx_date}|{amount:.2f}|{description}|{now_iso}".encode("utf-8")).hexdigest()[:24]
    else:
        tx_hash = compute_tx_hash(tx_date, amount, description)

    history_json = json.dumps(interrogation_history or [], ensure_ascii=False)

    try:
        cur.execute(
            """
            INSERT INTO transactions (
                tx_hash, tx_date, valuta_date, description, merchant, amount,
                category, tx_type, source, verdict, regret_score, user_excuse,
                ai_roast, interrogation_history, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                tx_hash,
                tx_date,
                valuta_date or tx_date,
                description.strip(),
                merchant.strip() or description.strip()[:35],
                round(float(amount), 2),
                category,
                tx_type,
                source,
                verdict,
                int(regret_score),
                user_excuse.strip(),
                ai_roast.strip(),
                history_json,
                now_iso,
            ),
        )
        conn.commit()
        row_id = cur.lastrowid
        conn.close()
        return True, row_id
    except sqlite3.IntegrityError:
        conn.close()
        return False, None


def update_transaction_verdict(
    tx_id: int,
    verdict: str,
    regret_score: int,
    user_excuse: str,
    ai_roast: str,
    interrogation_history: List[Dict[str, str]],
    category: Optional[str] = None,
) -> None:
    conn = get_connection()
    history_json = json.dumps(interrogation_history, ensure_ascii=False)
    if category:
        conn.execute(
            """
            UPDATE transactions
            SET verdict = ?, regret_score = ?, user_excuse = ?, ai_roast = ?,
                interrogation_history = ?, category = ?
            WHERE id = ?
            """,
            (verdict, int(regret_score), user_excuse, ai_roast, history_json, category, tx_id),
        )
    else:
        conn.execute(
            """
            UPDATE transactions
            SET verdict = ?, regret_score = ?, user_excuse = ?, ai_roast = ?,
                interrogation_history = ?
            WHERE id = ?
            """,
            (verdict, int(regret_score), user_excuse, ai_roast, history_json, tx_id),
        )
    conn.commit()
    conn.close()


def delete_transaction(tx_id: int) -> None:
    conn = get_connection()
    conn.execute("DELETE FROM transactions WHERE id = ?", (tx_id,))
    conn.commit()
    conn.close()


def bulk_update_transactions_by_ids(
    tx_ids: List[int],
    verdict: str,
    category: Optional[str] = None,
    user_excuse: str = "",
) -> int:
    """Updates multiple transactions by their IDs in one batch."""
    if not tx_ids:
        return 0
    conn = get_connection()
    cur = conn.cursor()
    regret = 85 if verdict == "Guilty / Bad Purchase" else (15 if verdict == "Justified" else 0)
    note = user_excuse.strip() if user_excuse.strip() else f"Batch classified as {verdict}."
    placeholders = ",".join("?" for _ in tx_ids)
    if category:
        cur.execute(
            f"""
            UPDATE transactions
            SET verdict = ?, regret_score = ?, user_excuse = ?, ai_roast = ?, category = ?
            WHERE id IN ({placeholders})
            """,
            [verdict, regret, user_excuse.strip(), note, category] + [int(x) for x in tx_ids],
        )
    else:
        cur.execute(
            f"""
            UPDATE transactions
            SET verdict = ?, regret_score = ?, user_excuse = ?, ai_roast = ?
            WHERE id IN ({placeholders})
            """,
            [verdict, regret, user_excuse.strip(), note] + [int(x) for x in tx_ids],
        )
    changed = cur.rowcount
    conn.commit()
    conn.close()
    return changed


def bulk_delete_transactions_by_ids(tx_ids: List[int]) -> int:
    if not tx_ids:
        return 0
    conn = get_connection()
    cur = conn.cursor()
    placeholders = ",".join("?" for _ in tx_ids)
    cur.execute(f"DELETE FROM transactions WHERE id IN ({placeholders})", [int(x) for x in tx_ids])
    changed = cur.rowcount
    conn.commit()
    conn.close()
    return changed


def bulk_update_merchant_verdict(merchant: str, verdict: str, category: Optional[str] = None) -> int:
    """Updates all expenses for a given canonical merchant to the specified verdict (and optional category)."""
    conn = get_connection()
    cur = conn.cursor()
    regret = 85 if verdict == "Guilty / Bad Purchase" else (15 if verdict == "Justified" else 0)
    note = f"Bulk classified as {verdict}."
    if category:
        cur.execute(
            """
            UPDATE transactions
            SET verdict = ?, regret_score = ?, ai_roast = ?, category = ?
            WHERE merchant = ? AND amount < 0
            """,
            (verdict, regret, note, category, merchant),
        )
    else:
        cur.execute(
            """
            UPDATE transactions
            SET verdict = ?, regret_score = ?, ai_roast = ?
            WHERE merchant = ? AND amount < 0
            """,
            (verdict, regret, note, merchant),
        )
    changed = cur.rowcount
    conn.commit()
    conn.close()
    return changed


def get_transactions_df(
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    verdict_filter: Optional[str] = None,
) -> pd.DataFrame:
    conn = get_connection()
    query = """
        SELECT t.*, c.tier as category_tier
        FROM transactions t
        LEFT JOIN categories c ON t.category = c.name
        WHERE 1=1
    """
    params: List[Any] = []
    if start_date:
        query += " AND t.tx_date >= ?"
        params.append(start_date)
    if end_date:
        query += " AND t.tx_date <= ?"
        params.append(end_date)
    if verdict_filter and verdict_filter != "All":
        query += " AND t.verdict = ?"
        params.append(verdict_filter)

    query += " ORDER BY t.tx_date DESC, t.id DESC"
    df = pd.read_sql_query(query, conn, params=params)
    conn.close()
    return df


def add_to_wishlist(
    item_name: str,
    price: float,
    category: str,
    urge_reason: str,
    ai_initial_warning: str,
    unlock_at: str,
) -> int:
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO wishlist_vault (item_name, price, category, urge_reason, ai_initial_warning, created_at, unlock_at, status)
        VALUES (?, ?, ?, ?, ?, ?, ?, 'Locked')
        """,
        (
            item_name.strip(),
            round(float(price), 2),
            category,
            urge_reason.strip(),
            ai_initial_warning.strip(),
            datetime.now().isoformat(timespec="seconds"),
            unlock_at,
        ),
    )
    conn.commit()
    row_id = cur.lastrowid
    conn.close()
    return row_id


def get_wishlist_df() -> pd.DataFrame:
    conn = get_connection()
    df = pd.read_sql_query("SELECT * FROM wishlist_vault ORDER BY id DESC", conn)
    conn.close()
    return df


def update_wishlist_status(item_id: int, status: str) -> None:
    conn = get_connection()
    conn.execute("UPDATE wishlist_vault SET status = ? WHERE id = ?", (status, item_id))
    conn.commit()
    conn.close()


def sync_db_to_github(
    github_token: str = "",
    github_repo: str = "",
    github_branch: str = "main",
    remote_path: str = "data/budget_2027.db",
    commit_message: Optional[str] = None,
) -> Tuple[bool, str]:
    if not os.path.exists(DB_PATH):
        init_db()

    msg = commit_message or f"chore(db): sync ledger [{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}]"

    # 1. If a GitHub Personal Access Token is provided (e.g. on Streamlit Cloud), push via GitHub REST API
    if github_token and github_repo:
        with open(DB_PATH, "rb") as f:
            content_b64 = base64.b64encode(f.read()).decode("utf-8")

        api_url = f"https://api.github.com/repos/{github_repo.strip()}/contents/{remote_path.strip('/')}"
        headers = {
            "Authorization": f"Bearer {github_token.strip()}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }

        sha = None
        get_resp = requests.get(api_url, headers=headers, params={"ref": github_branch}, timeout=15)
        if get_resp.status_code == 200:
            sha = get_resp.json().get("sha")
        elif get_resp.status_code not in (404,):
            return False, f"GitHub read error ({get_resp.status_code})"

        payload: Dict[str, Any] = {
            "message": msg,
            "content": content_b64,
            "branch": github_branch,
        }
        if sha:
            payload["sha"] = sha

        put_resp = requests.put(api_url, headers=headers, json=payload, timeout=20)
        if put_resp.status_code in (200, 201):
            return True, f"Synced to {github_repo} ({github_branch})."
        return False, f"GitHub push failed ({put_resp.status_code})."

    # 2. Local Git CLI fallback (uses local git credentials automatically without needing a token)
    if os.path.exists(os.path.join(ROOT_DIR, ".git")):
        try:
            subprocess.run(["git", "add", "data/budget_2027.db"], cwd=ROOT_DIR, check=True, capture_output=True)
            commit_res = subprocess.run(["git", "commit", "-m", msg], cwd=ROOT_DIR, capture_output=True, text=True)
            if "nothing to commit" in (commit_res.stdout or "") + (commit_res.stderr or ""):
                return True, "Database already up to date in Git."
            push_res = subprocess.run(["git", "push", "origin", github_branch], cwd=ROOT_DIR, capture_output=True, text=True, timeout=20)
            if push_res.returncode == 0:
                return True, "Committed and pushed DB to GitHub via local Git."
            return False, f"Committed locally, push error: {push_res.stderr[:120]}"
        except Exception as e:
            return False, f"Local Git sync error: {e}"

    return False, "Missing GitHub token or local Git repository."


def pull_db_from_github(
    github_token: str = "",
    github_repo: str = "",
    github_branch: str = "main",
    remote_path: str = "data/budget_2027.db",
) -> Tuple[bool, str]:
    if github_token and github_repo:
        api_url = f"https://api.github.com/repos/{github_repo.strip()}/contents/{remote_path.strip('/')}"
        headers = {
            "Authorization": f"Bearer {github_token.strip()}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }

        resp = requests.get(api_url, headers=headers, params={"ref": github_branch}, timeout=15)
        if resp.status_code != 200:
            return False, f"Fetch failed ({resp.status_code})."

        data = resp.json()
        content_b64 = data.get("content", "")
        if not content_b64:
            return False, "Remote file is empty."

        raw_bytes = base64.b64decode(content_b64)
        os.makedirs(DB_DIR, exist_ok=True)
        with open(DB_PATH, "wb") as f:
            f.write(raw_bytes)

        return True, f"Restored from {github_repo} ({github_branch})."

    if os.path.exists(os.path.join(ROOT_DIR, ".git")):
        try:
            pull_res = subprocess.run(["git", "pull", "--rebase", "origin", github_branch], cwd=ROOT_DIR, capture_output=True, text=True, timeout=20)
            if pull_res.returncode == 0:
                return True, "Pulled latest DB from GitHub via local Git."
            return False, f"Git pull failed: {pull_res.stderr[:120]}"
        except Exception as e:
            return False, f"Local Git pull error: {e}"

    return False, "Missing GitHub token or local Git repository."
