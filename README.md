# New-Grad Job Email Alerts

Polls **350+ direct company career sites** (`Greenhouse`, `Lever`, `Ashby`, `Workday`, `SmartRecruiters`, `Amazon`, `Netflix`) plus **LinkedIn** (with 3-layer anti-repost filtering), filters strictly for **US undergraduate / Bachelor's new-grad** Data Scientist, Data Analyst, and AI/ML Engineer roles (`0–2 years`, no Master's/PhD-only, no visa-sponsorship rejections), scores and tailors bullets against `VietN_Resume.pdf` using **Gemini** (with Groq failover), and emails HTML digests immediately.

---

## Project Structure

```text
job_email/
├── .github/workflows/job_alerts.yml  # 24/7 cloud runner (every 15 min)
├── config/
│   ├── config.yaml                   # Pipeline settings, filters & search terms
│   ├── profile.yaml                  # Candidate resume (VietN_Resume.pdf)
│   ├── ats_boards.yaml               # 350+ company career boards catalog
│   └── allowed_companies.yaml        # Priority / H-1B sponsor allowlist
├── data/
│   └── seen_jobs.db                  # SQLite state & cross-source dedupe history
├── scripts/
│   └── build_ats_boards.py           # Regenerates config/ats_boards.yaml
├── src/
│   ├── filters/                      # Location, company, repost, title, newgrad, sponsorship
│   ├── scoring/                      # Gemini + Groq scorer & ATS bullet customizer
│   ├── sources/                      # Greenhouse, Lever, Ashby, Workday, SR, Amazon, Netflix, LinkedIn
│   ├── board_loader.py               # Loads config/ats_boards.yaml
│   ├── db.py                         # SQLite persistence & clone-repost detection
│   ├── dedupe.py                     # Cross-source job fingerprint deduplication
│   ├── emailer.py                    # HTML + plain-text digest builder & Gmail SMTP
│   ├── models.py                     # Job dataclass
│   └── pipeline.py                   # Batch filtering, scoring, and emailing
├── main.py                           # CLI entrypoint
└── requirements.txt                  # Python dependencies
```

---

## Run in the Cloud 24/7 with GitHub Actions

In your GitHub repo (`https://github.com/viet0901/job-email-alerts`), go to **Settings → Secrets and variables → Actions → New repository secret** and add:

| Secret Name | Value (from your `.env`) |
|---|---|
| `GEMINI_API_KEY` | Your Gemini API key |
| `GROQ_API_KEY` | Your Groq API key (automatic fallback) |
| `SMTP_USER` | Your Gmail address |
| `SMTP_PASSWORD` | Your 16-character Gmail App Password |
| `EMAIL_TO` | Comma-separated recipient emails |

---

## Local Commands

```bash
# Verify Gmail SMTP
.venv/bin/python main.py --test-email

# Score + print without sending email
.venv/bin/python main.py --dry-run

# Live run
.venv/bin/python main.py
```
