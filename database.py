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
    ("Online Shopping & PayPal", "Impulse", 100.0, ""),
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
    "eur_inr_rate": "90.0",
    "wise_invest_inr_per_300": "12000.0",
    "monthly_pac_fondi_eur": "100.0",
    "github_repo": "arnab-polimi/budget",
    "github_branch": "main",
    "github_token_b64": "",
    "gemini_api_key_b64": "",
}


def encode_secret(plain: str) -> str:
    if not plain or not plain.strip():
        return ""
    return base64.b64encode(plain.strip().encode("utf-8")).decode("utf-8")


def decode_secret(encoded: str) -> str:
    if not encoded or not encoded.strip():
        return ""
    try:
        return base64.b64decode(encoded.strip().encode("utf-8")).decode("utf-8")
    except Exception:
        return ""


def get_local_git_credential_token() -> str:
    """Retrieves the local Git Credential Manager OAuth token for github.com if available."""
    try:
        proc = subprocess.run(
            ["git", "credential", "fill"],
            input="protocol=https\nhost=github.com\n\n",
            capture_output=True,
            text=True,
            timeout=3,
        )
        if proc.returncode == 0:
            for line in proc.stdout.splitlines():
                if line.startswith("password="):
                    return line.split("=", 1)[1].strip()
    except Exception:
        pass
    return ""


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
            recurrence TEXT DEFAULT 'One-Time',
            created_at TEXT NOT NULL
        )
        """
    )

    # Ensure recurrence column exists on legacy DBs
    cur.execute("PRAGMA table_info(transactions)")
    existing_cols = {row["name"] for row in cur.fetchall()}
    if "recurrence" not in existing_cols:
        cur.execute("ALTER TABLE transactions ADD COLUMN recurrence TEXT DEFAULT 'One-Time'")

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
        # Ensure any newly added default categories exist
        cur.executemany(
            "INSERT OR IGNORE INTO categories (name, tier, monthly_limit, icon) VALUES (?, ?, ?, ?)",
            DEFAULT_CATEGORIES,
        )
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
    recurrence: str = "One-Time",
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
                ai_roast, interrogation_history, recurrence, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                recurrence,
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
    recurrence: Optional[str] = None,
) -> None:
    conn = get_connection()
    history_json = json.dumps(interrogation_history, ensure_ascii=False)
    fields = [
        "verdict = ?",
        "regret_score = ?",
        "user_excuse = ?",
        "ai_roast = ?",
        "interrogation_history = ?",
    ]
    params: List[Any] = [verdict, int(regret_score), user_excuse, ai_roast, history_json]
    if category:
        fields.append("category = ?")
        params.append(category)
    if recurrence:
        fields.append("recurrence = ?")
        params.append(recurrence)
    params.append(tx_id)
    conn.execute(
        f"UPDATE transactions SET {', '.join(fields)} WHERE id = ?",
        params,
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
    recurrence: Optional[str] = None,
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
    fields = ["verdict = ?", "regret_score = ?", "user_excuse = ?", "ai_roast = ?"]
    params: List[Any] = [verdict, regret, user_excuse.strip(), note]
    if category:
        fields.append("category = ?")
        params.append(category)
    if recurrence:
        fields.append("recurrence = ?")
        params.append(recurrence)
    cur.execute(
        f"UPDATE transactions SET {', '.join(fields)} WHERE id IN ({placeholders})",
        params + [int(x) for x in tx_ids],
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


def bulk_update_merchant_verdict(
    merchant: str,
    verdict: str,
    category: Optional[str] = None,
    recurrence: Optional[str] = None,
) -> int:
    """Updates all expenses for a given canonical merchant to the specified verdict (and optional category/recurrence)."""
    conn = get_connection()
    cur = conn.cursor()
    regret = 85 if verdict == "Guilty / Bad Purchase" else (15 if verdict == "Justified" else 0)
    note = f"Bulk classified as {verdict}."
    fields = ["verdict = ?", "regret_score = ?", "ai_roast = ?"]
    params: List[Any] = [verdict, regret, note]
    if category:
        fields.append("category = ?")
        params.append(category)
    if recurrence:
        fields.append("recurrence = ?")
        params.append(recurrence)
    params.append(merchant)
    cur.execute(
        f"UPDATE transactions SET {', '.join(fields)} WHERE merchant = ? AND amount < 0",
        params,
    )
    changed = cur.rowcount
    conn.commit()
    conn.close()
    return changed


def reclassify_all_transactions() -> int:
    """
    Re-applies smart merchant normalization, category classification, and recurrence detection
    across all stored transactions while preserving already-audited verdicts.
    """
    import bper_importer

    conn = get_connection()
    rows = conn.execute("SELECT id, tx_date, description, amount, verdict, recurrence FROM transactions").fetchall()

    # Track distinct months per normalized merchant to detect true recurring commitments (>= 3 months)
    variable_discretionary = {
        "Amazon",
        "Glovo",
        "Deliveroo",
        "Revolut Top-Up / Transfer",
        "Wise Transfer",
        "Decathlon",
        "MediaWorld",
        "PayPal (Temu)",
        "La Locomotiva",
        "Ricarica Carta Prepagata",
    }
    merchant_months: Dict[str, set] = {}
    parsed_updates: List[Tuple[int, str, str, str, str, str]] = []
    for r in rows:
        desc = str(r["description"])
        amt = float(r["amount"])
        m = bper_importer.clean_bper_merchant(desc)
        cat, default_verd = bper_importer.classify_bper_transaction(desc, amt)
        rec = bper_importer.infer_default_recurrence(desc, m, cat, amt)
        ym = str(r["tx_date"])[:7]
        if amt < 0:
            merchant_months.setdefault(m, set()).add(ym)
        parsed_updates.append((int(r["id"]), m, cat, default_verd, rec, str(r["verdict"])))

    cur = conn.cursor()
    updated = 0
    for tx_id, m, cat, default_verd, rec, old_verd in parsed_updates:
        is_frequent_committed = (m not in variable_discretionary) and (len(merchant_months.get(m, set())) >= 3)
        final_rec = "Recurring" if (rec == "Recurring" or is_frequent_committed) else "One-Time"
        final_verd = old_verd
        if old_verd == "Pending Review" and default_verd in ("Essential Pass", "Justified"):
            final_verd = default_verd
        cur.execute(
            "UPDATE transactions SET merchant = ?, category = ?, recurrence = ?, verdict = ? WHERE id = ?",
            (m, cat, final_rec, final_verd, tx_id),
        )
        updated += 1

    conn.commit()
    conn.close()
    return updated


def get_transactions_df(
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    verdict_filter: Optional[str] = None,
    recurrence_filter: Optional[str] = None,
) -> pd.DataFrame:
    conn = get_connection()
    query = """
        SELECT t.*, COALESCE(t.recurrence, 'One-Time') as recurrence_clean, c.tier as category_tier
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
    if recurrence_filter and recurrence_filter != "All":
        query += " AND COALESCE(t.recurrence, 'One-Time') = ?"
        params.append(recurrence_filter)

    query += " ORDER BY t.tx_date DESC, t.id DESC"
    df = pd.read_sql_query(query, conn, params=params)
    if not df.empty and "recurrence_clean" in df.columns:
        df["recurrence"] = df["recurrence_clean"]
        df.drop(columns=["recurrence_clean"], inplace=True)
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

    effective_token = github_token.strip()
    if not effective_token:
        effective_token = decode_secret(get_setting("github_token_b64", "")) or get_local_git_credential_token()
    effective_repo = github_repo.strip() or get_setting("github_repo", "arnab-polimi/budget")
    effective_branch = github_branch.strip() or get_setting("github_branch", "main")

    msg = commit_message or f"chore(db): sync ledger [{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}]"

    # 1. Push via GitHub REST API using inbuilt/stored/GCM token
    if effective_token and effective_repo:
        with open(DB_PATH, "rb") as f:
            content_b64 = base64.b64encode(f.read()).decode("utf-8")

        api_url = f"https://api.github.com/repos/{effective_repo}/contents/{remote_path.strip('/')}"
        headers = {
            "Authorization": f"Bearer {effective_token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }

        sha = None
        get_resp = requests.get(api_url, headers=headers, params={"ref": effective_branch}, timeout=15)
        if get_resp.status_code == 200:
            sha = get_resp.json().get("sha")
        elif get_resp.status_code not in (404,):
            return False, f"GitHub read error ({get_resp.status_code})"

        payload: Dict[str, Any] = {
            "message": msg,
            "content": content_b64,
            "branch": effective_branch,
        }
        if sha:
            payload["sha"] = sha

        put_resp = requests.put(api_url, headers=headers, json=payload, timeout=20)
        if put_resp.status_code in (200, 201):
            return True, f"Synced to {effective_repo} ({effective_branch})."
        return False, f"GitHub push failed ({put_resp.status_code})."

    # 2. Local Git CLI fallback (uses local git credentials automatically without needing a token)
    if os.path.exists(os.path.join(ROOT_DIR, ".git")):
        try:
            subprocess.run(["git", "add", "data/budget_2027.db"], cwd=ROOT_DIR, check=True, capture_output=True)
            commit_res = subprocess.run(["git", "commit", "-m", msg], cwd=ROOT_DIR, capture_output=True, text=True)
            if "nothing to commit" in (commit_res.stdout or "") + (commit_res.stderr or ""):
                return True, "Database already up to date in Git."
            push_res = subprocess.run(["git", "push", "origin", effective_branch], cwd=ROOT_DIR, capture_output=True, text=True, timeout=20)
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
    effective_token = github_token.strip()
    if not effective_token:
        effective_token = decode_secret(get_setting("github_token_b64", "")) or get_local_git_credential_token()
    effective_repo = github_repo.strip() or get_setting("github_repo", "arnab-polimi/budget")
    effective_branch = github_branch.strip() or get_setting("github_branch", "main")

    if effective_token and effective_repo:
        api_url = f"https://api.github.com/repos/{effective_repo}/contents/{remote_path.strip('/')}"
        headers = {
            "Authorization": f"Bearer {effective_token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }

        resp = requests.get(api_url, headers=headers, params={"ref": effective_branch}, timeout=15)
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

        return True, f"Restored from {effective_repo} ({effective_branch})."

    if os.path.exists(os.path.join(ROOT_DIR, ".git")):
        try:
            pull_res = subprocess.run(["git", "pull", "--rebase", "origin", effective_branch], cwd=ROOT_DIR, capture_output=True, text=True, timeout=20)
            if pull_res.returncode == 0:
                return True, "Pulled latest DB from GitHub via local Git."
            return False, f"Git pull failed: {pull_res.stderr[:120]}"
        except Exception as e:
            return False, f"Local Git pull error: {e}"

    return False, "Missing GitHub token or local Git repository."
