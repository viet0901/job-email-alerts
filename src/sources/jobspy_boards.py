from __future__ import annotations

import re
import sqlite3
from pathlib import Path
from typing import Any

from src.filters.repost import is_reposted_listing
from src.models import Job

# Sites supported by python-jobspy that we use as extra boards.
SUPPORTED_SITES = {
    "google",
    "indeed",
    "glassdoor",
    "zip_recruiter",
    "linkedin",
}

# LinkedIn assigns monotonically increasing 10-digit jobPosting IDs when a job is
# FIRST created (~550k–650k IDs per 24h globally, ~25k/hour).
# When an employer reposts/bumps an old job, LinkedIn's guest HTML hides the word
# "Reposted" and resets the displayed time to "X hours ago", but the jobPosting ID
# stays at its original creation number (millions behind today's frontier ID).
_MAX_LINKEDIN_JOB_ID: int = 0
_LINKEDIN_MAX_24H_ID_LAG = 1_100_000  # ~42 hours of global LinkedIn job IDs


def _seed_max_linkedin_id() -> int:
    """Seed the LinkedIn ID high-water mark from seen_jobs.db if available."""
    global _MAX_LINKEDIN_JOB_ID
    if _MAX_LINKEDIN_JOB_ID > 0:
        return _MAX_LINKEDIN_JOB_ID
    root = Path(__file__).resolve().parents[2]
    db_path = next(
        (p for p in (root / "data" / "seen_jobs.db", root / "seen_jobs.db") if p.exists()),
        root / "data" / "seen_jobs.db",
    )
    if not db_path.exists():
        return _MAX_LINKEDIN_JOB_ID
    try:
        conn = sqlite3.connect(db_path)
        rows = conn.execute(
            "SELECT job_id FROM seen_jobs WHERE job_id LIKE 'li:%'"
        ).fetchall()
        conn.close()
        for (jid,) in rows:
            num = _extract_linkedin_numeric_id(str(jid))
            if num and num > _MAX_LINKEDIN_JOB_ID:
                _MAX_LINKEDIN_JOB_ID = num
    except Exception:  # noqa: BLE001
        pass
    return _MAX_LINKEDIN_JOB_ID


def _extract_linkedin_numeric_id(text: str) -> int | None:
    if not text:
        return None
    matches = re.findall(r"(\d{9,11})", str(text))
    if not matches:
        return None
    try:
        return int(matches[-1])
    except ValueError:
        return None


def _update_max_linkedin_id_from_card(job_card: Any, job_id: str | None = None) -> int:
    global _MAX_LINKEDIN_JOB_ID
    _seed_max_linkedin_id()
    if job_id:
        num = _extract_linkedin_numeric_id(job_id)
        if num and num > _MAX_LINKEDIN_JOB_ID:
            _MAX_LINKEDIN_JOB_ID = num
    if job_card is not None:
        root = getattr(job_card, "parent", None) or job_card
        try:
            for tag in root.find_all("div", class_="base-search-card"):
                urn = tag.get("data-entity-urn") or ""
                num = _extract_linkedin_numeric_id(urn)
                if num and num > _MAX_LINKEDIN_JOB_ID:
                    _MAX_LINKEDIN_JOB_ID = num
        except Exception:  # noqa: BLE001
            pass
    return _MAX_LINKEDIN_JOB_ID


def _parse_card_claimed_hours(job_card: Any) -> float | None:
    """Parse '45 minutes ago' / '5 hours ago' / '1 day ago' from a LinkedIn card."""
    time_tag = _linkedin_card_time(job_card)
    if time_tag is None:
        return None
    text = time_tag.get_text(" ", strip=True).lower()
    m = re.search(r"(\d+)\s*(minute|min|hour|hr|day|week|month)", text)
    if not m:
        if "just now" in text or "moment" in text:
            return 0.1
        return None
    val = float(m.group(1))
    unit = m.group(2)
    if unit.startswith("min"):
        return val / 60.0
    if unit.startswith("h"):
        return val
    if unit.startswith("d"):
        return val * 24.0
    if unit.startswith("w"):
        return val * 24.0 * 7.0
    if unit.startswith("m"):
        return val * 24.0 * 30.0
    return None


def _is_linkedin_id_repost(
    job_id: str | int | None,
    *,
    max_id: int | None = None,
    claimed_hours: float | None = None,
    max_hours_old: float = 24.0,
) -> tuple[bool, int]:
    """
    Detect LinkedIn reposts using LinkedIn's monotonic jobPosting ID sequence.
    Returns (is_repost, id_lag_behind_frontier).
    """
    num_id = (
        job_id
        if isinstance(job_id, int)
        else _extract_linkedin_numeric_id(str(job_id or ""))
    )
    frontier = max_id if max_id is not None else _seed_max_linkedin_id()
    if not num_id or not frontier or frontier <= num_id:
        return False, 0

    lag = frontier - num_id

    # If the card claims it was posted minutes or a few hours ago, its ID must be
    # near the current frontier (~25k–30k IDs/hour, plus generous slack).
    if claimed_hours is not None:
        if claimed_hours <= 3.0 and lag > 350_000:
            return True, lag
        if claimed_hours <= 12.0 and lag > 650_000:
            return True, lag

    # Hard ceiling based on configured hours_old window (default 24h -> 1.1M IDs).
    allowed_lag = int(max(1.0, max_hours_old / 24.0) * _LINKEDIN_MAX_24H_ID_LAG)
    if lag > allowed_lag:
        return True, lag
    return False, lag


def fetch_jobspy_jobs(
    *,
    sites: list[str],
    search_terms: list[str],
    location: str = "United States",
    results_per_search: int = 20,
    hours_old: int | None = 72,
    google_search_terms: list[str] | None = None,
    linkedin_fetch_description: bool = False,
    id_prefix: str | None = None,
) -> list[Job]:
    """
    Search one or more job boards via python-jobspy (Google Jobs, Indeed, LinkedIn, etc.).
    """
    try:
        from jobspy import scrape_jobs
    except ImportError as exc:
        raise RuntimeError(
            "python-jobspy is not installed. Run: pip install python-jobspy"
        ) from exc

    _seed_max_linkedin_id()
    _patch_linkedin_repost_detection(hours_old=float(hours_old or 24))

    site_list = [s.strip().lower() for s in sites if s and s.strip().lower() in SUPPORTED_SITES]
    if not site_list:
        return []

    prefix = id_prefix or ("+".join(site_list) if len(site_list) > 1 else site_list[0])
    seen: set[str] = set()
    all_jobs: list[Job] = []
    errors: list[str] = []

    terms = [t.strip() for t in (search_terms or []) if t and str(t).strip()]
    g_terms = [
        t.strip()
        for t in (google_search_terms or [])
        if t and str(t).strip()
    ]

    use_google = "google" in site_list
    non_google = [s for s in site_list if s != "google"]

    def _scrape(
        *,
        site_name: list[str],
        search_term: str | None,
        google_search_term: str | None,
        label: str,
    ) -> None:
        nonlocal all_jobs
        try:
            kwargs: dict[str, Any] = dict(
                site_name=site_name,
                location=location,
                results_wanted=results_per_search,
                hours_old=hours_old,
                country_indeed="USA",
                linkedin_fetch_description=linkedin_fetch_description,
            )
            if google_search_term:
                kwargs["google_search_term"] = google_search_term
            if search_term:
                kwargs["search_term"] = search_term
            df = scrape_jobs(**kwargs)
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{label}: {exc}")
            return

        if df is None or getattr(df, "empty", True):
            return

        for _, row in df.iterrows():
            job = _row_to_job(
                row,
                search_term=label,
                id_prefix=prefix,
                max_hours_old=float(hours_old or 24),
            )
            if not job or job.id in seen:
                continue
            seen.add(job.id)
            all_jobs.append(job)

    if non_google and terms:
        for term in terms:
            _scrape(
                site_name=non_google,
                search_term=term,
                google_search_term=None,
                label=term,
            )

    if use_google:
        queries = g_terms or [
            f"{term} jobs near {location} since last week" for term in terms
        ]
        for query in queries:
            _scrape(
                site_name=["google"],
                search_term=None,
                google_search_term=query,
                label=query,
            )

    # Final pass across all fetched LinkedIn jobs using the highest ID seen in the entire batch
    if "linkedin" in site_list and _MAX_LINKEDIN_JOB_ID > 0:
        for job in all_jobs:
            if job.is_reposted:
                continue
            is_rep, lag = _is_linkedin_id_repost(
                job.id,
                max_id=_MAX_LINKEDIN_JOB_ID,
                max_hours_old=float(hours_old or 24),
            )
            if is_rep:
                job.is_reposted = True
                job.raw["linkedin_id_lag"] = lag
                job.raw["listing_type"] = "repost"

    if not all_jobs and errors:
        raise RuntimeError(
            f"JobSpy ({','.join(site_list)}) failed: " + "; ".join(errors[:5])
        )
    if errors:
        print(
            f"  JobSpy ({','.join(site_list)}) partial errors "
            f"({len(errors)}): {errors[:3]}"
        )
    return all_jobs


def _row_to_job(
    row: Any,
    *,
    search_term: str,
    id_prefix: str,
    max_hours_old: float = 24.0,
) -> Job | None:
    global _MAX_LINKEDIN_JOB_ID
    title = str(row.get("title") or "").strip()
    if not title:
        return None

    company = str(row.get("company") or "").strip() or "Unknown"
    job_url = str(row.get("job_url") or row.get("job_url_direct") or "").strip()
    raw_id = str(row.get("id") or "").strip()
    if not raw_id:
        raw_id = job_url or f"{company}:{title}:{search_term}"
    raw_id = raw_id.replace(" ", "_")[:180]

    description = str(row.get("description") or "").strip()
    if len(description) > 6000:
        description = description[:6000] + "…"

    location = str(row.get("location") or "").strip()
    is_remote = row.get("is_remote")
    work_model = "Remote" if is_remote is True else ""
    site = str(row.get("site") or id_prefix).strip().lower() or id_prefix

    posted_ms = _parse_posted_ms(row.get("date_posted") or row.get("date"))
    listing_raw = row.get("listing_type")
    try:
        if listing_raw is None or (isinstance(listing_raw, float) and listing_raw != listing_raw):
            listing_type = ""
        else:
            listing_type = str(listing_raw).strip().lower()
            if listing_type in {"nan", "none", "nat"}:
                listing_type = ""
    except Exception:  # noqa: BLE001
        listing_type = ""
    is_reposted = "repost" in listing_type

    num_id = _extract_linkedin_numeric_id(raw_id) or _extract_linkedin_numeric_id(job_url)
    if site == "linkedin" and num_id:
        if num_id > _MAX_LINKEDIN_JOB_ID:
            _MAX_LINKEDIN_JOB_ID = num_id
        id_rep, lag = _is_linkedin_id_repost(
            num_id,
            max_id=_MAX_LINKEDIN_JOB_ID,
            max_hours_old=max_hours_old,
        )
        if id_rep:
            is_reposted = True
            listing_type = "repost"

    if not is_reposted:
        probe = Job(
            id="probe",
            title=title,
            company=company,
            qualifications=description,
            source=site,
            raw={"listing_type": listing_type},
        )
        is_reposted = is_reposted_listing(probe)

    raw = dict(row) if hasattr(row, "to_dict") else {}
    if listing_type:
        raw["listing_type"] = listing_type

    return Job(
        id=f"{id_prefix}:{raw_id}",
        title=title,
        company=company,
        location=location,
        work_model=work_model,
        apply_url=job_url,
        qualifications=description,
        h1b_sponsored=None,
        salary=str(row.get("min_amount") or row.get("max_amount") or "") or "",
        category=search_term,
        source=site,
        posted_date_ms=posted_ms,
        is_reposted=is_reposted,
        raw=raw,
    )


def _parse_posted_ms(value: Any) -> int | None:
    if value is None:
        return None
    try:
        if isinstance(value, float) and value != value:  # NaN
            return None
    except Exception:  # noqa: BLE001
        pass

    from datetime import date, datetime, timezone

    if isinstance(value, datetime):
        dt = value if value.tzinfo else value.replace(tzinfo=timezone.utc)
        return int(dt.timestamp() * 1000)
    if isinstance(value, date):
        dt = datetime(value.year, value.month, value.day, tzinfo=timezone.utc)
        return int(dt.timestamp() * 1000)
    if isinstance(value, (int, float)):
        num = float(value)
        if num > 1e12:
            return int(num)
        if num > 1e9:
            return int(num * 1000)
        return None
    text = str(value).strip()
    if not text or text.lower() in {"nan", "none", "nat"}:
        return None
    try:
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return int(dt.timestamp() * 1000)
    except ValueError:
        return None


_LINKEDIN_REPOST_PATCHED = False
_PATCHED_MAX_HOURS_OLD: float = 24.0
_REPOST_HOUR_MS = 60 * 60 * 1000


def _parse_linkedin_timestamps(html: str) -> dict:
    """Pull listedAt / originalListedAt / Reposted flags from a LinkedIn job-view page."""
    out: dict = {
        "is_reposted": False,
        "original_listed_at_ms": None,
        "listed_at_ms": None,
    }
    if not html:
        return out

    def _ms(pattern: str) -> int | None:
        match = re.search(pattern, html)
        if not match:
            return None
        try:
            value = int(match.group(1))
        except ValueError:
            return None
        if value < 1e11:  # seconds
            value *= 1000
        return value

    orig = _ms(r'"originalListedAt"\s*:\s*(\d{10,13})') or _ms(
        r'"originallyListedAt"\s*:\s*(\d{10,13})'
    )
    listed = _ms(r'"listedAt"\s*:\s*(\d{10,13})')
    out["original_listed_at_ms"] = orig
    out["listed_at_ms"] = listed
    if orig and listed and (listed - orig) > _REPOST_HOUR_MS:
        out["is_reposted"] = True
    if re.search(r'"isReposted"\s*:\s*true', html, re.I):
        out["is_reposted"] = True
    if re.search(
        r"(posted-time-ago__text[^<]{0,80}|job-search-card__listdate[^<]{0,80}|>)\s*"
        r"re-?posted\b",
        html,
        re.I,
    ):
        out["is_reposted"] = True
    return out


def _linkedin_card_time(job_card):
    if job_card is None:
        return None
    metadata = job_card.find("div", class_="base-search-card__metadata")
    root = metadata or job_card
    return root.find("time")


def _linkedin_card_is_reposted(job_card) -> bool:
    """LinkedIn cards that explicitly say 'Reposted X ago'."""
    if job_card is None:
        return False
    time_tag = _linkedin_card_time(job_card)
    if time_tag is not None:
        text = time_tag.get_text(" ", strip=True).lower()
        if "repost" in text:
            return True
    for tag in job_card.find_all(["time", "span"]):
        classes = " ".join(tag.get("class") or []).lower()
        text = tag.get_text(" ", strip=True).lower()
        if "repost" in text:
            return True
        if ("listdate" in classes or "listed-date" in classes or "posted-time" in classes) and (
            "repost" in text
        ):
            return True
    text = job_card.get_text(" ", strip=True).lower()
    return "reposted" in text or "re-posted" in text


def _patch_linkedin_repost_detection(*, hours_old: float = 24.0) -> None:
    """
    Teach python-jobspy to detect LinkedIn reposts via:
      1. Monotonic jobPosting ID lag vs. current frontier ID (catches guest HTML bumps
         where LinkedIn hides 'Reposted' and shows '1 hour ago' on old job IDs).
      2. Card / detail HTML 'Reposted' text & originalListedAt timestamps.
    Also skips fetching full detail pages for cards already identified as reposts.
    """
    global _LINKEDIN_REPOST_PATCHED, _PATCHED_MAX_HOURS_OLD
    _PATCHED_MAX_HOURS_OLD = float(hours_old or 24.0)
    if _LINKEDIN_REPOST_PATCHED:
        return
    try:
        from datetime import datetime as _dt

        from jobspy.linkedin import LinkedIn
    except ImportError:
        return

    orig_process = LinkedIn._process_job
    orig_details = LinkedIn._get_job_details

    def _get_job_details(self, job_id: str) -> dict:
        captured: dict[str, str] = {}
        orig_get = self.session.get

        def _cap_get(*args, **kwargs):
            resp = orig_get(*args, **kwargs)
            captured["html"] = getattr(resp, "text", "") or ""
            return resp

        self.session.get = _cap_get  # type: ignore[method-assign]
        try:
            details = orig_details(self, job_id)
        finally:
            self.session.get = orig_get  # type: ignore[method-assign]
        self._last_repost_meta = _parse_linkedin_timestamps(captured.get("html", ""))
        return details

    def _process_job(self, job_card, job_id, full_descr):
        frontier = _update_max_linkedin_id_from_card(job_card, str(job_id))
        claimed_hours = _parse_card_claimed_hours(job_card)
        card_reposted = _linkedin_card_is_reposted(job_card)
        id_reposted, id_lag = _is_linkedin_id_repost(
            job_id,
            max_id=frontier,
            claimed_hours=claimed_hours,
            max_hours_old=_PATCHED_MAX_HOURS_OLD,
        )

        # If the card is already a known repost (by ID lag or card text), skip the slow
        # /jobs/view/{id} detail request so we don't waste time or trigger 429s on reposts.
        effective_full_descr = False if (card_reposted or id_reposted) else full_descr
        self._last_repost_meta = {}
        job_post = orig_process(self, job_card, job_id, effective_full_descr)
        if job_post is None:
            return None

        time_tag = _linkedin_card_time(job_card)
        if job_post.date_posted is None and time_tag is not None:
            raw_dt = time_tag.get("datetime")
            if raw_dt:
                try:
                    job_post.date_posted = _dt.strptime(str(raw_dt)[:10], "%Y-%m-%d").date()
                except ValueError:
                    pass
        elif isinstance(job_post.date_posted, _dt):
            job_post.date_posted = job_post.date_posted.date()

        meta = getattr(self, "_last_repost_meta", {}) or {}
        is_reposted = bool(card_reposted or id_reposted or meta.get("is_reposted"))
        orig_ms = meta.get("original_listed_at_ms")
        if orig_ms and job_post.date_posted is not None:
            dp = job_post.date_posted
            listed_ms = int(_dt(dp.year, dp.month, dp.day).timestamp() * 1000)
            if listed_ms - orig_ms > _REPOST_HOUR_MS:
                is_reposted = True
        if orig_ms:
            try:
                job_post.date_posted = _dt.utcfromtimestamp(orig_ms / 1000.0).date()
            except (OSError, OverflowError, ValueError):
                pass

        if is_reposted:
            job_post.listing_type = "repost"
            desc = job_post.description or ""
            reason_note = (
                f"Reposted (LinkedIn ID lag={id_lag:,}).\n"
                if id_reposted
                else "Reposted.\n"
            )
            if "reposted" not in desc.lower():
                job_post.description = reason_note + desc
        return job_post

    LinkedIn._get_job_details = _get_job_details  # type: ignore[method-assign]
    LinkedIn._process_job = _process_job  # type: ignore[method-assign]
    _LINKEDIN_REPOST_PATCHED = True
