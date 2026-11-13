#!/usr/bin/env python3
"""Poll large/mid-size company career sites, filter, score, and email ASAP."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import yaml
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.board_loader import boards_for, load_ats_boards
from src.db import JobDB
from src.emailer import send_test_email
from src.pipeline import process_batch
from src.state_sync import pull_and_merge_remote_state, push_remote_state
from src.sources.ashby import fetch_all_boards as fetch_ashby_boards
from src.sources.first_party import fetch_all_first_party
from src.sources.greenhouse import fetch_all_boards
from src.sources.handshake import fetch_handshake_jobs
from src.sources.jobspy_boards import fetch_jobspy_jobs
from src.sources.lever import fetch_all_boards as fetch_lever_boards
from src.sources.linkedin import fetch_linkedin_jobs
from src.sources.smartrecruiters import fetch_all_boards as fetch_smartrecruiters_boards
from src.sources.workday import fetch_all_boards as fetch_workday_boards


def _resolve_config_path(filename: str) -> Path:
    for candidate in (ROOT / "config" / filename, ROOT / filename):
        if candidate.exists():
            return candidate
    return ROOT / "config" / filename


def _resolve_db_path() -> Path:
    data_db = ROOT / "data" / "seen_jobs.db"
    legacy_db = ROOT / "seen_jobs.db"
    if data_db.exists() or not legacy_db.exists():
        data_db.parent.mkdir(parents=True, exist_ok=True)
        return data_db
    return legacy_db


def load_yaml(path: Path) -> dict:
    with path.open(encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def load_allowed_companies(config: dict) -> list[str]:
    """Load allowlist from config list and/or allowed_companies.yaml."""
    names = [str(x).strip() for x in (config.get("allowed_companies") or []) if x]
    rel = config.get("allowed_companies_file")
    if rel:
        path = _resolve_config_path(Path(str(rel)).name)
        if not path.exists():
            path = ROOT / str(rel)
        if path.exists():
            data = load_yaml(path)
            extra = data.get("allowed_companies") if isinstance(data, dict) else data
            for x in extra or []:
                s = str(x).strip()
                if s:
                    names.append(s)
    seen: set[str] = set()
    out: list[str] = []
    for n in names:
        key = n.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(n)
    return out


def fetch_jobs(config: dict, *, phase: str = "all", allow_empty: bool = False) -> list:
    """Pull from enabled sources.

    phase=fast: company career sites (Greenhouse/Lever/Ashby/Workday/SmartRecruiters + Amazon/Netflix/Microsoft).
    phase=slow: LinkedIn / Indeed / Handshake aggregators (off by default).
    phase=all: both.
    """
    sources = config.get("sources") or {}
    all_jobs: list = []
    seen_ids: set[str] = set()
    ats_catalog = load_ats_boards(ROOT, config)

    def _add(batch: list, label: str) -> None:
        added = 0
        for job in batch:
            if job.id in seen_ids:
                continue
            seen_ids.add(job.id)
            all_jobs.append(job)
            added += 1
        print(f"Fetched {added} jobs from {label} (raw={len(batch)})")

    do_fast = phase in {"all", "fast"}
    do_slow = phase in {"all", "slow"}

    gh = sources.get("greenhouse") or {}
    if do_fast and gh.get("enabled", False):
        boards = boards_for(sources, ats_catalog, "greenhouse")
        print(f"  Greenhouse boards: {len(boards)}")
        try:
            _add(
                fetch_all_boards(boards, workers=int(gh.get("workers") or 12)),
                "Greenhouse",
            )
        except Exception as exc:  # noqa: BLE001
            print(f"Greenhouse fetch failed: {exc}")

    lv = sources.get("lever") or {}
    if do_fast and lv.get("enabled", False):
        boards = boards_for(sources, ats_catalog, "lever")
        print(f"  Lever boards: {len(boards)}")
        try:
            _add(
                fetch_lever_boards(boards, workers=int(lv.get("workers") or 10)),
                "Lever",
            )
        except Exception as exc:  # noqa: BLE001
            print(f"Lever fetch failed: {exc}")

    ash = sources.get("ashby") or {}
    if do_fast and ash.get("enabled", False):
        boards = boards_for(sources, ats_catalog, "ashby")
        print(f"  Ashby boards: {len(boards)}")
        try:
            _add(
                fetch_ashby_boards(boards, workers=int(ash.get("workers") or 10)),
                "Ashby",
            )
        except Exception as exc:  # noqa: BLE001
            print(f"Ashby fetch failed: {exc}")

    wd = sources.get("workday") or {}
    if do_fast and wd.get("enabled", False):
        boards = boards_for(sources, ats_catalog, "workday")
        print(f"  Workday boards: {len(boards)}")
        try:
            _add(
                fetch_workday_boards(
                    boards,
                    default_search_terms=wd.get("search_terms"),
                    default_limit=int(wd.get("limit") or 20),
                    board_workers=int(wd.get("board_workers") or 8),
                ),
                "Workday",
            )
        except Exception as exc:  # noqa: BLE001
            print(f"Workday fetch failed: {exc}")

    sr = sources.get("smartrecruiters") or {}
    if do_fast and sr.get("enabled", False):
        boards = boards_for(sources, ats_catalog, "smartrecruiters")
        print(f"  SmartRecruiters boards: {len(boards)}")
        try:
            _add(
                fetch_smartrecruiters_boards(
                    boards,
                    workers=int(sr.get("workers") or 6),
                ),
                "SmartRecruiters",
            )
        except Exception as exc:  # noqa: BLE001
            print(f"SmartRecruiters fetch failed: {exc}")

    fp = sources.get("first_party") or {}
    if do_fast and fp.get("enabled", False):
        try:
            _add(fetch_all_first_party(fp), "Company career sites")
        except Exception as exc:  # noqa: BLE001
            print(f"First-party career sites failed: {exc}")

    li = sources.get("linkedin") or {}
    if do_slow and li.get("enabled", False):
        try:
            _add(
                fetch_linkedin_jobs(
                    search_terms=li.get("search_terms") or [],
                    location=li.get("location") or "United States",
                    results_per_search=int(li.get("results_per_search") or 20),
                    hours_old=li.get("hours_old", 72),
                ),
                "LinkedIn",
            )
        except Exception as exc:  # noqa: BLE001
            print(f"LinkedIn fetch failed: {exc}")

    for key, label in (
        ("google", "Google Jobs"),
        ("indeed", "Indeed"),
        ("glassdoor", "Glassdoor"),
        ("zip_recruiter", "ZipRecruiter"),
    ):
        cfg = sources.get(key) or {}
        if not do_slow or not cfg.get("enabled", False):
            continue
        try:
            _add(
                fetch_jobspy_jobs(
                    sites=[key],
                    search_terms=cfg.get("search_terms") or [],
                    google_search_terms=cfg.get("google_search_terms"),
                    location=cfg.get("location") or "United States",
                    results_per_search=int(cfg.get("results_per_search") or 20),
                    hours_old=cfg.get("hours_old", 72),
                    id_prefix=key[:2] if key != "google" else "gj",
                ),
                label,
            )
        except Exception as exc:  # noqa: BLE001
            print(f"{label} fetch failed: {exc}")

    hs = sources.get("handshake") or {}
    if do_slow and hs.get("enabled", False):
        try:
            _add(
                fetch_handshake_jobs(
                    cities=hs.get("cities") or [],
                    search_terms=hs.get("search_terms") or [],
                    results_wanted=int(hs.get("results_wanted") or 40),
                    hours_old=hs.get("hours_old", 72),
                ),
                "Handshake",
            )
        except Exception as exc:  # noqa: BLE001
            print(f"Handshake fetch failed: {exc}")

    if not all_jobs:
        if allow_empty:
            print(f"No jobs fetched in phase={phase}")
            return []
        raise RuntimeError(
            "No jobs fetched from any enabled source. "
            "Check sources.* in config.yaml"
        )
    return all_jobs


def run(*, dry_run: bool = False, force_rescore: bool = False) -> int:
    load_dotenv(ROOT / ".env")
    config = load_yaml(_resolve_config_path("config.yaml"))
    profile = load_yaml(_resolve_config_path("profile.yaml"))

    threshold = float(config.get("score_threshold", 0.80))
    max_jobs = int(
        config.get("max_jobs_per_email")
        or config.get("max_emails_per_run")
        or 8
    )
    max_score = int(config.get("max_score_per_run", 40))
    title_families = config.get("title_families") or {}
    companies = config.get("company_priority") or []
    preferred_locations = config.get("preferred_locations") or []
    interest_keywords = config.get("interest_keywords") or []
    require_us = bool(config.get("require_us", True))
    reject_unknown_location = bool(config.get("reject_unknown_location", False))
    require_new_grad = bool(config.get("require_new_grad", True))
    strict_new_grad = bool(config.get("strict_new_grad", True))
    undergrad_only = bool(config.get("undergrad_only", True))
    newgrad_require_title_signal = bool(
        config.get("newgrad_require_title_signal", True)
    )
    blocked_companies = list(config.get("blocked_companies") or [])
    allowed_companies = load_allowed_companies(config)
    require_allowed_company = bool(config.get("require_allowed_company", False))
    max_job_age_minutes = float(config.get("max_job_age_minutes", 360))
    require_recent_timestamp = bool(config.get("require_recent_timestamp", True))
    catchup_grace_minutes = float(config.get("catchup_grace_minutes", 1440))
    max_repost_age_minutes = float(config.get("max_repost_age_days", 14)) * 24 * 60
    send_priority_now = bool(config.get("send_priority_ds_immediately", True))
    score_state = {"used": 0}

    reject_reposts = bool(config.get("reject_reposts", True))
    fresh_kwargs = dict(
        max_age_minutes=max_job_age_minutes,
        require_timestamp=require_recent_timestamp,
        catchup_grace_minutes=catchup_grace_minutes,
        max_repost_age_minutes=max_repost_age_minutes,
        reject_reposts=reject_reposts,
    )
    db_path = _resolve_db_path()
    db = JobDB(db_path)
    pull_and_merge_remote_state(ROOT, db)
    filled = db.backfill_fingerprints()
    if filled:
        print(f"DB: backfilled {filled} fingerprints for cross-source dedupe")
    emailed_fps = db.emailed_fingerprints()
    retention_days = int(config.get("db_retention_days", 7))
    if retention_days > 0:
        purged = db.purge_older_than(retention_days)
        if purged:
            print(f"DB cleanup: deleted {purged} jobs older than {retention_days} days")

    batch_kwargs = dict(
        db=db,
        profile=profile,
        title_families=title_families,
        companies=companies,
        preferred_locations=preferred_locations,
        interest_keywords=interest_keywords,
        blocked_companies=blocked_companies,
        allowed_companies=allowed_companies,
        require_allowed_company=require_allowed_company,
        require_us=require_us,
        reject_unknown_location=reject_unknown_location,
        require_new_grad=require_new_grad,
        strict_new_grad=strict_new_grad,
        undergrad_only=undergrad_only,
        newgrad_require_title_signal=newgrad_require_title_signal,
        threshold=threshold,
        max_jobs=max_jobs,
        max_score=max_score,
        max_job_age_minutes=max_job_age_minutes,
        fresh_kwargs=fresh_kwargs,
        emailed_fps=emailed_fps,
        send_priority_now=send_priority_now,
        dry_run=dry_run,
        force_rescore=force_rescore,
        score_state=score_state,
    )

    totals = {
        "total": 0,
        "fresh_eligible": 0,
        "already_seen": 0,
        "title_reject": 0,
        "location_reject": 0,
        "company_reject": 0,
        "newgrad_reject": 0,
        "freshness_reject": 0,
        "repost_reject": 0,
        "sponsor_reject": 0,
        "scored": 0,
        "score_capped": 0,
        "emailed": 0,
        "duplicates": 0,
    }

    print("--- phase 1: company career sites ---")
    fast_jobs = fetch_jobs(config, phase="fast", allow_empty=True)
    fast_stats = process_batch(fast_jobs, phase="fast", **batch_kwargs)
    for k, v in fast_stats.items():
        totals[k] = totals.get(k, 0) + v

    print("--- phase 2: LinkedIn & extra boards ---")
    slow_jobs = fetch_jobs(config, phase="slow", allow_empty=True)
    slow_stats = process_batch(slow_jobs, phase="slow", **batch_kwargs)
    for k, v in slow_stats.items():
        totals[k] = totals.get(k, 0) + v

    if totals["total"] == 0 and not fast_jobs and not slow_jobs:
        db.close()
        raise RuntimeError(
            "No jobs fetched from any enabled source. Check sources.* in config.yaml"
        )

    print(
        "Done. "
        f"total={totals['total']} fresh={totals['fresh_eligible']} "
        f"seen={totals['already_seen']} dups={totals['duplicates']} "
        f"title_reject={totals['title_reject']} location_reject={totals['location_reject']} "
        f"company_reject={totals['company_reject']} "
        f"newgrad_reject={totals['newgrad_reject']} "
        f"repost_reject={totals.get('repost_reject', 0)} "
        f"freshness_reject={totals['freshness_reject']} "
        f"sponsor_reject={totals['sponsor_reject']} "
        f"scored={totals['scored']} score_capped={totals['score_capped']} "
        f"emailed={totals['emailed']}"
    )
    db.close()
    if not dry_run:
        push_remote_state(ROOT, db_path)
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Newgrad job email alerts")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Score and print emails without sending SMTP mail",
    )
    parser.add_argument(
        "--force-rescore",
        action="store_true",
        help="Ignore seen_jobs.db and reprocess all fetched jobs (still updates DB)",
    )
    parser.add_argument(
        "--test-email",
        action="store_true",
        help="Send one test email via SMTP and exit (does not poll jobs)",
    )
    parser.add_argument(
        "--purge-db",
        action="store_true",
        help="Only purge seen_jobs older than db_retention_days, then exit",
    )
    args = parser.parse_args()
    if args.test_email:
        load_dotenv(ROOT / ".env")
        try:
            send_test_email()
        except Exception as exc:  # noqa: BLE001
            print(f"TEST EMAIL FAILED: {exc}")
            raise SystemExit(1) from exc
        raise SystemExit(0)
    if args.purge_db:
        load_dotenv(ROOT / ".env")
        config = load_yaml(_resolve_config_path("config.yaml"))
        days = int(config.get("db_retention_days", 7))
        db = JobDB(_resolve_db_path())
        n = db.purge_older_than(days)
        db.close()
        print(f"Purged {n} jobs older than {days} days")
        raise SystemExit(0)
    raise SystemExit(run(dry_run=args.dry_run, force_rescore=args.force_rescore))


if __name__ == "__main__":
    main()
