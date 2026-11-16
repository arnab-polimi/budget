# 🚨 SENTINEL 2027 — No-Mercy AI Budgeting & BPER Bank Tracker

**Sentinel 2027** is a Streamlit budgeting app built to make sure **every single cent is logged** and **every questionable purchase is interrogated**.

## ✨ Key Features

1. **🤖 AI Financial Interrogator ("The Courtroom")**
   - Connects to **Google Gemini** (`gemini-2.5-flash`), **OpenAI** (`gpt-4o-mini`), or **local Ollama**, plus includes an instant **built-in Offline Prosecutor** so it works out of the box even without an API key.
   - Calculates the **real cost** of every purchase: how many **hours of your working life** you traded for it, and how much **10-year / 20-year S&P 500 compound wealth** you lost.
   - Holds suspect purchases in `Pending Review` until you defend yourself in live chat. Weak excuses ("I was tired", "It was on sale") get called out and stamped `Guilty / Bad Purchase`.

2. **🏦 Smart BPER Banca Importer (Past & Ongoing Expenses)**
   - Upload your `.xlsx`, `.xls`, or `.csv` statement exported from **BPER Smart Web** or the **BPER Mobile App**.
   - Automatically skips BPER's top bank metadata rows, parses Italian dates (`DD/MM/YYYY`) and numbers (`-1.234,56 €`), cleans noisy `PAGAMENTO POS PRESSO...` merchant strings, and deduplicates using SHA-256 hashes.
   - Recognizes 100+ Italian merchants (`Esselunga`, `Conad`, `Enel`, `Glovo`, `Deliveroo`, `Zara`, `Amazon`, `Trenitalia`, `Satispay`, etc.) — giving essentials an `Essential Pass` while sending delivery, shopping, and impulse buys straight to the **Interrogation Room**.

3. **⚡ 3-Second Mobile & Desktop Quick Log**
   - Log cash, coffee, or immediate card spends on the go with an instant **Guilt Check** and live **Opportunity Cost Slider**.

4. **🧊 24-Hour Impulse Cooling-Off Vault**
   - Tempted to buy something non-essential? Lock it in the Vault for 24 hours. Skipping it adds to your **Dodged Bullets Savings Score**.

5. **☁️ Always-On Availability via SQLite + GitHub Sync**
   - All data is stored locally in `data/budget_2027.db` (SQLite).
   - Includes built-in **GitHub REST API Push/Pull & Auto-Sync** in the sidebar so when hosted on **Streamlit Community Cloud** (which is free and accessible 24/7 from your phone), every change can be automatically committed back to your private GitHub repository!

---

## 🚀 Running Locally

```bash
pip install -r requirements.txt
streamlit run app.py
```

---

## 🌐 Making It Available 24/7 Everywhere (Streamlit Cloud + GitHub)

1. Create a **private GitHub repository** (e.g., `your-username/budget_2027`) and push this folder:
   ```bash
   git init
   git add .
   git commit -m "Initial commit: Sentinel 2027 Budget App"
   git branch -M main
   git remote add origin https://github.com/your-username/budget_2027.git
   git push -u origin main
   ```
2. Go to [share.streamlit.io](https://share.streamlit.io/) and deploy `app.py` from your repo.
3. In Streamlit Cloud -> **App Settings** -> **Secrets**, paste the contents of `.streamlit/secrets.example.toml` with:
   - Your `GEMINI_API_KEY` (or `OPENAI_API_KEY`)
   - Your `GITHUB_TOKEN` (a GitHub Personal Access Token with `repo` write permissions) and `GITHUB_REPO = "your-username/budget_2027"`
4. Check **"Auto-push DB to GitHub on changes"** in the sidebar — now your SQLite database is permanently saved to your GitHub repo every time you log a cent or import a BPER statement!
