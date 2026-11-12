from __future__ import annotations

import html
import os
import smtplib
from datetime import datetime, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from src.models import Job
from src.scoring.llm import ScoreResult, ensure_ats_guidance


def _tier_label(score: float) -> str:
    pct = int(round(score * 100))
    if pct >= 90:
        return "APPLY NOW"
    if pct >= 80:
        return "HIGH PRIORITY"
    if pct >= 70:
        return "REVIEW"
    return "LOW"


def _tier_color(tier: str) -> str:
    return {
        "APPLY NOW": "#0B6E4F",
        "HIGH PRIORITY": "#1D4E89",
        "REVIEW": "#8A5A00",
        "LOW": "#555555",
    }.get(tier, "#333333")


def _location_line(job: Job) -> str:
    parts = [p for p in (job.location, job.work_model) if p]
    return " · ".join(parts) if parts else "Location not listed"


def _esc(text: str) -> str:
    return html.escape(text or "", quote=True)


def _chip_list_html(items: list[str], *, bg: str, fg: str, border: str, empty_label: str) -> str:
    if not items:
        return f'<span style="font-size:12px;color:#64748B;">{_esc(empty_label)}</span>'
    chips = []
    for kw in items[:8]:
        chips.append(
            f'<span style="display:inline-block;margin:2px 6px 4px 0;padding:3px 9px;'
            f'border-radius:999px;background:{bg};color:{fg};border:1px solid {border};'
            f'font-size:12px;font-weight:600;">{_esc(kw)}</span>'
        )
    return "".join(chips)


def build_digest(items: list[tuple[Job, ScoreResult]]) -> tuple[str, str, str]:
    """
    Build one digest email for multiple jobs.
    Returns (subject, plain_text, html).
    """
    if not items:
        raise ValueError("build_digest requires at least one job")

    items = [(job, ensure_ats_guidance(job, score)) for job, score in items]
    items = sorted(items, key=lambda pair: pair[1].overall, reverse=True)
    n = len(items)
    top = items[0]
    top_pct = int(round(top[1].overall * 100))
    top_tier = _tier_label(top[1].overall)
    when = datetime.now(timezone.utc).strftime("%b %d, %Y %H:%M UTC")

    from src.dedupe import is_data_scientist_title

    ds_hit = is_data_scientist_title(top[0])
    if n == 1:
        job, score = top
        prefix = "PRIORITY DS" if ds_hit else top_tier
        subject = (
            f"{prefix} — {job.title} at {job.company} | {top_pct}% · New grad alert"
        )
    else:
        ds_note = " · DS first" if ds_hit else ""
        subject = (
            f"{n} new-grad matches · top {top_pct}% — {top[0].title} @ {top[0].company}"
            f"{ds_note}"
        )

    # ---- plain text ----
    plain_parts = [
        f"New-grad job digest ({n} role{'s' if n != 1 else ''}) — undergrad / bachelor's",
        f"Generated: {when}",
        "",
        "US · undergrad new-grad · recent postings · no-sponsorship roles excluded",
        "",
    ]
    for i, (job, score) in enumerate(items, 1):
        pct = int(round(score.overall * 100))
        tier = _tier_label(score.overall)
        evidence = score.visa_evidence or []
        evidence_txt = "\n".join(f"    • {e}" for e in evidence[:4]) or "    • (none)"
        matched_txt = ", ".join(score.matched_keywords or []) or "(none detected)"
        missing_txt = ", ".join(score.missing_keywords or []) or "(no extra JD tools flagged)"
        bullets_txt = (
            "\n".join(f"    • {b}" for b in (score.tailored_bullets or [])[:3])
            or "    • (none)"
        )
        plain_parts.extend(
            [
                f"{'─' * 52}",
                f"{i}. {job.title}",
                f"   {job.company}",
                f"   {_location_line(job)}",
                f"   Score: {pct}/100 · {tier} · source: {job.source}",
                f"   Sponsorship field: {job.h1b_sponsored or 'Unknown'}",
                f"   Seniority: {score.seniority or 'unknown'} · Family: {score.role_family or 'unknown'}",
                "",
                f"   Why you match",
                f"   {score.brief_why or 'See listing for details.'}",
                "",
                f"   Gap",
                f"   {score.gaps or 'None noted.'}",
                "",
                f"   ATS Keywords Already Matched (put near top of Skills)",
                f"   {matched_txt}",
                "",
                f"   ATS Keyword Gap (mirror/add before submitting)",
                f"   {missing_txt}",
                "",
                f"   Tailored Resume Bullets (copy/adapt before applying)",
                bullets_txt,
                "",
                f"   Visa evidence",
                evidence_txt,
                "",
                f"   Apply: {job.apply_url}",
                "",
            ]
        )
    plain_parts.append("— job_email digest")
    plain = "\n".join(plain_parts)

    # ---- HTML ----
    cards = []
    for i, (job, score) in enumerate(items, 1):
        pct = int(round(score.overall * 100))
        tier = _tier_label(score.overall)
        color = _tier_color(tier)
        evidence_html = "".join(
            f"<li>{_esc(e)}</li>" for e in (score.visa_evidence or [])[:4]
        ) or "<li>(none)</li>"
        matched_chips = _chip_list_html(
            score.matched_keywords or [],
            bg="#ECFDF5",
            fg="#065F46",
            border="#A7F3D0",
            empty_label="Core Python / SQL / ML",
        )
        missing_chips = _chip_list_html(
            score.missing_keywords or [],
            bg="#FFFBEB",
            fg="#92400E",
            border="#FDE68A",
            empty_label="No extra JD keywords missing",
        )
        bullets_html = "".join(
            f'<li style="margin:0 0 6px 0;">{_esc(b)}</li>'
            for b in (score.tailored_bullets or [])[:3]
        )
        apply = _esc(job.apply_url)
        cards.append(
            f"""
            <tr>
              <td style="padding:0 0 20px 0;">
                <table role="presentation" width="100%" cellspacing="0" cellpadding="0"
                       style="border:1px solid #E5E7EB;border-radius:10px;overflow:hidden;background:#FFFFFF;">
                  <tr>
                    <td style="background:#F8FAFC;padding:14px 18px;border-bottom:1px solid #E5E7EB;">
                      <div style="font-size:12px;letter-spacing:0.04em;color:{color};font-weight:700;">
                        #{i} · { _esc(tier) } · {pct}% match
                      </div>
                      <div style="font-size:18px;line-height:1.3;color:#0F172A;font-weight:700;margin-top:6px;">
                        {_esc(job.title)}
                      </div>
                      <div style="font-size:14px;color:#334155;margin-top:4px;">
                        {_esc(job.company)}
                        <span style="color:#94A3B8;"> · </span>
                        {_esc(_location_line(job))}
                      </div>
                    </td>
                  </tr>
                  <tr>
                    <td style="padding:16px 18px;font-size:14px;line-height:1.55;color:#1E293B;">
                      <p style="margin:0 0 10px 0;">
                        <strong>Why you match</strong><br/>
                        {_esc(score.brief_why or "See listing for details.")}
                      </p>
                      <p style="margin:0 0 12px 0;">
                        <strong>Gap</strong><br/>
                        {_esc(score.gaps or "None noted.")}
                      </p>

                      <div style="background:#F8FAFC;border:1px solid #E2E8F0;border-radius:8px;padding:12px 14px;margin:0 0 14px 0;">
                        <div style="font-size:12px;font-weight:800;letter-spacing:0.04em;color:#0F172A;text-transform:uppercase;margin-bottom:8px;">
                          ATS Tailoring Checklist (VietN_Resume.pdf)
                        </div>
                        <div style="margin:0 0 8px 0;">
                          <div style="font-size:12px;font-weight:700;color:#065F46;margin-bottom:4px;">
                            ✓ Already on VietN_Resume.pdf:
                          </div>
                          {matched_chips}
                        </div>
                        <div style="margin:0 0 10px 0;">
                          <div style="font-size:12px;font-weight:700;color:#92400E;margin-bottom:4px;">
                            + Missing JD Keywords to Mirror / Add:
                          </div>
                          {missing_chips}
                        </div>
                        <div>
                          <div style="font-size:12px;font-weight:700;color:#1E3A8A;margin-bottom:4px;">
                            Tailored Bullets (Adapted from Your Resume):
                          </div>
                          <ul style="margin:0 0 0 18px;padding:0;font-size:13px;color:#1E293B;">
                            {bullets_html}
                          </ul>
                        </div>
                      </div>

                      <p style="margin:0 0 6px 0;"><strong>Visa / sponsorship</strong>
                        <span style="color:#64748B;">
                          (field: {_esc(job.h1b_sponsored or "Unknown")} ·
                          OPT {score.opt_fit:.2f} · sponsor {score.sponsorship_fit:.2f})
                        </span>
                      </p>
                      <ul style="margin:0 0 14px 18px;padding:0;color:#475569;">{evidence_html}</ul>
                      <table role="presentation" cellspacing="0" cellpadding="0">
                        <tr>
                          <td style="border-radius:8px;background:{color};">
                            <a href="{apply}"
                               style="display:inline-block;padding:10px 16px;color:#FFFFFF;
                                      text-decoration:none;font-weight:700;font-size:13px;">
                              Apply directly →
                            </a>
                          </td>
                        </tr>
                      </table>
                      <p style="margin:10px 0 0 0;font-size:12px;color:#94A3B8;">
                        Source: {_esc(job.source)} · Level: {_esc(score.seniority or "unknown")}
                        · Family: {_esc(score.role_family or "unknown")}
                      </p>
                    </td>
                  </tr>
                </table>
              </td>
            </tr>
            """
        )

    html_body = f"""<!DOCTYPE html>
<html>
<head><meta charset="utf-8"/><meta name="viewport" content="width=device-width"/></head>
<body style="margin:0;padding:0;background:#EEF2F7;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Helvetica,Arial,sans-serif;">
  <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="background:#EEF2F7;padding:24px 12px;">
    <tr>
      <td align="center">
        <table role="presentation" width="640" cellspacing="0" cellpadding="0" style="max-width:640px;width:100%;">
          <tr>
            <td style="padding:8px 4px 18px 4px;">
              <div style="font-size:22px;font-weight:800;color:#0F172A;letter-spacing:-0.02em;">
                Undergrad new-grad matches
              </div>
              <div style="font-size:13px;color:#64748B;margin-top:4px;">
                {n} role{'s' if n != 1 else ''} · US · undergrad new-grad · { _esc(when) }
              </div>
            </td>
          </tr>
          {''.join(cards)}
          <tr>
            <td style="padding:8px 4px 0 4px;font-size:12px;color:#94A3B8;line-height:1.5;">
              Sent by your local job_email digest. Only roles clearing your score threshold are included.
            </td>
          </tr>
        </table>
      </td>
    </tr>
  </table>
</body>
</html>
"""
    return subject, plain, html_body


# Back-compat single-job helper used by older call sites / tests
def build_email(job: Job, score: ScoreResult) -> tuple[str, str]:
    subject, plain, _html = build_digest([(job, score)])
    return subject, plain


def _smtp_settings() -> dict[str, str | int | list[str]]:
    host = os.getenv("SMTP_HOST", "smtp.gmail.com").strip()
    port = int(os.getenv("SMTP_PORT", "587"))
    user = os.getenv("SMTP_USER", "").strip()
    password = os.getenv("SMTP_PASSWORD", "").replace(" ", "").strip()
    raw_to = os.getenv("EMAIL_TO", user).strip()
    email_to = [p.strip() for p in raw_to.replace(";", ",").split(",") if p.strip()]
    email_from = os.getenv("EMAIL_FROM", user).strip()
    return {
        "host": host,
        "port": port,
        "user": user,
        "password": password,
        "email_to": email_to,
        "email_from": email_from,
    }


def send_email(subject: str, body: str, html_body: str | None = None) -> None:
    cfg = _smtp_settings()
    user = str(cfg["user"])
    password = str(cfg["password"])
    recipients = list(cfg["email_to"])
    email_to = ", ".join(recipients)
    email_from = str(cfg["email_from"])
    host = str(cfg["host"])
    port = int(cfg["port"])

    if not user or not password or not recipients:
        raise RuntimeError(
            "SMTP_USER, SMTP_PASSWORD, and EMAIL_TO must be set in .env to send email"
        )

    if html_body:
        msg = MIMEMultipart("alternative")
        msg["From"] = email_from
        msg["To"] = email_to
        msg["Subject"] = subject
        msg.attach(MIMEText(body, "plain", "utf-8"))
        msg.attach(MIMEText(html_body, "html", "utf-8"))
    else:
        msg = MIMEMultipart()
        msg["From"] = email_from
        msg["To"] = email_to
        msg["Subject"] = subject
        msg.attach(MIMEText(body, "plain", "utf-8"))

    try:
        with smtplib.SMTP(host, port, timeout=30) as server:
            server.ehlo()
            server.starttls()
            server.ehlo()
            server.login(user, password)
            server.sendmail(email_from, recipients, msg.as_string())
    except smtplib.SMTPAuthenticationError as exc:
        raise RuntimeError(
            "Gmail login failed. Use a 16-character App Password (not your normal "
            "Gmail password), and make sure SMTP_USER matches that Google account. "
            f"Details: {exc}"
        ) from exc
    except smtplib.SMTPException as exc:
        raise RuntimeError(f"SMTP send failed: {exc}") from exc


def send_digest(items: list[tuple[Job, ScoreResult]]) -> str:
    subject, plain, html_body = build_digest(items)
    send_email(subject, plain, html_body=html_body)
    return subject


def send_test_email() -> None:
    """Send one HTML sample digest so you can verify formatting + SMTP."""
    sample_job = Job(
        id="test",
        title="Data Scientist, New Grad (2027)",
        company="Capital One",
        location="New York, NY",
        work_model="Hybrid",
        apply_url="https://example.com/jobs/1",
        qualifications=(
            "Bachelor's degree in Computer Science, Statistics, or Data Science. "
            "0-2 years of experience in Python, SQL, Tableau, A/B testing, Snowflake, "
            "scikit-learn, credit risk modeling, and machine learning."
        ),
        h1b_sponsored="Yes",
        source="workday",
    )
    sample_score = ScoreResult(
        role_family="data_scientist",
        seniority="entry_level",
        opt_fit=0.9,
        sponsorship_fit=0.85,
        brief_why="Strong SQL/Python/ML overlap with your profile for an undergrad new-grad Data Scientist role.",
        gaps="Highlight A/B testing, Snowflake, and credit risk modeling keywords on your resume.",
        visa_evidence=["No explicit no-sponsorship clause detected in sample."],
        overall=0.88,
        used_llm=False,
    )
    subject = send_digest([(sample_job, sample_score)])
    cfg = _smtp_settings()
    print(f"Test digest emailed to {cfg['email_to']}: {subject}")


def dry_run_print(subject: str, body: str, html_body: str | None = None) -> None:
    print("=" * 60)
    print("SUBJECT:", subject)
    print("-" * 60)
    print(body)
    if html_body:
        print("-" * 60)
        print(f"(HTML body: {len(html_body)} chars)")
    print("=" * 60)
