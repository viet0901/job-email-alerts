# New-Grad Job Email Alerts

Polls **350+ direct company career sites** (`Greenhouse`, `Lever`, `Ashby`, `Workday`, `SmartRecruiters`, `Amazon`, `Netflix`) plus **LinkedIn** (with 3-layer anti-repost filtering), filters strictly for **US undergraduate / Bachelor's new-grad** Data Scientist, Data Analyst, and AI/ML Engineer roles (`0–2 years`, no Master's/PhD-only, no visa-sponsorship rejections), scores and tailors bullets against `VietN_Resume.pdf` using **Gemini** (with Groq failover), and emails HTML digests immediately.

---

## Run in the Cloud 24/7 with GitHub Actions

A workflow is pre-configured in `.github/workflows/job_alerts.yml` to run **every 15 minutes** and automatically persist `seen_jobs.db` back to the repository so you never get duplicate emails.

### 1. Create a GitHub Repository & Push
Create a new repository on GitHub (e.g., `job-email-alerts`), then run:

```bash
git remote add origin https://github.com/<your-username>/job-email-alerts.git
git push -u origin main
```

### 2. Add Repository Secrets
In your GitHub repo, go to **Settings → Secrets and variables → Actions → New repository secret** and add:

| Secret Name | Value (from your `.env`) |
|---|---|
| `GEMINI_API_KEY` | Your Gemini API key |
| `GROQ_API_KEY` | Your Groq API key (automatic fallback) |
| `SMTP_USER` | Your Gmail address |
| `SMTP_PASSWORD` | Your 16-character Gmail App Password |
| `EMAIL_TO` | Comma-separated recipient emails |

### 3. Trigger a Test Run
Go to the **Actions** tab on GitHub → **New-Grad Job Email Alerts** → **Run workflow** → choose `live`, `dry-run`, or `test-email`.

---

## Local Setup & Commands

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

```bash
# Verify Gmail SMTP
python main.py --test-email

# Score + print without sending email
python main.py --dry-run

# Live run
python main.py
```

### Local Cron (every 15 min)

```cron
*/15 * * * * cd /Users/minhvietnguyen/Documents/job_email && .venv/bin/python main.py >> logs/run.log 2>&1
```
