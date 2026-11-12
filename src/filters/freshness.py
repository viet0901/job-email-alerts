from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime, timezone

from src.filters.repost import is_reposted_listing
from src.models import Job


@dataclass
class FreshnessVerdict:
    accept: bool
    reason: str
    age_minutes: float | None = None


def _parse_iso_ms(value: str | None) -> float | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.timestamp() * 1000
    except ValueError:
        return None


def _age_minutes(ts_ms: float, now_ms: float) -> float:
    return (now_ms - ts_ms) / 60_000.0


def is_fresh_job(
    job: Job,
    *,
    max_age_minutes: float = 360,
    require_timestamp: bool = True,
    first_seen_at: str | None = None,
    now_ms: float | None = None,
    mode: str = "discover",
    catchup_grace_minutes: float = 1440,
    max_repost_age_minutes: float = 20160,  # 14 days
    reject_reposts: bool = False,
) -> FreshnessVerdict:
    """
    mode=discover:
      - True new post: posted_date within max_age
      - Never-seen + recent ATS update: updated_date within max_age AND
        posted within max_repost_age (Greenhouse bumps updated_at on old jobs;
        career pages often show that as "recent") — disabled when reject_reposts
      - If first_seen exists: also require first_seen within max_age (no re-alert)

    mode=catchup (scored, never emailed):
      - updated_date within max_age (and posted within max_repost_age), OR
      - posted within max_age, OR
      - first_seen within catchup_grace (digest overflow)
    """
    now = now_ms if now_ms is not None else time.time() * 1000
    if reject_reposts and is_reposted_listing(job):
        return FreshnessVerdict(False, "linkedin_repost")
    posted_ms = float(job.posted_date_ms) if job.posted_date_ms is not None else None
    original_ms = (
        float(job.original_posted_date_ms)
        if getattr(job, "original_posted_date_ms", None) is not None
        else None
    )
    if original_ms is not None:
        posted_ms = min(posted_ms, original_ms) if posted_ms is not None else original_ms
    updated_ms = (
        float(job.updated_date_ms) if job.updated_date_ms is not None else None
    )
    first_ms = _parse_iso_ms(first_seen_at)

    def _ok(age: float) -> bool:
        return -2 <= age <= max_age_minutes

    def _repost_ok() -> bool:
        if posted_ms is None:
            return True
        return _age_minutes(posted_ms, now) <= max_repost_age_minutes

    if mode == "catchup":
        # Never-emailed high scores: recent ATS activity is enough (we already liked them).
        if updated_ms is not None:
            upd_age = _age_minutes(updated_ms, now)
            if _ok(upd_age):
                return FreshnessVerdict(
                    True, f"catchup_updated:{upd_age:.1f}m", upd_age
                )
        if posted_ms is not None:
            src_age = _age_minutes(posted_ms, now)
            if _ok(src_age):
                return FreshnessVerdict(
                    True, f"catchup_source:{src_age:.1f}m", src_age
                )
        if first_ms is not None:
            fs_age = _age_minutes(first_ms, now)
            if -2 <= fs_age <= catchup_grace_minutes:
                return FreshnessVerdict(
                    True, f"catchup_first_seen:{fs_age:.1f}m", fs_age
                )
        if require_timestamp and posted_ms is None and updated_ms is None and first_ms is None:
            return FreshnessVerdict(False, "missing_timestamp")
        return FreshnessVerdict(False, "catchup_expired")

    # discover mode
    if first_ms is not None:
        # Already known — only alert on true recent post, not ATS bumps
        timestamps: list[tuple[str, float]] = [("first_seen", first_ms)]
        if posted_ms is not None:
            timestamps.append(("source", posted_ms))
        label, ts = min(timestamps, key=lambda pair: pair[1])
        age_min = _age_minutes(ts, now)
        if age_min < -2:
            return FreshnessVerdict(False, "future_timestamp", age_min)
        if age_min > max_age_minutes:
            return FreshnessVerdict(False, f"too_old:{label}:{age_min:.1f}m", age_min)
        return FreshnessVerdict(True, f"fresh:{label}:{age_min:.1f}m", age_min)

    # Never seen before — require true first-publish date when rejecting reposts
    if posted_ms is not None:
        src_age = _age_minutes(posted_ms, now)
        if _ok(src_age):
            return FreshnessVerdict(True, f"fresh:source:{src_age:.1f}m", src_age)
        if reject_reposts:
            return FreshnessVerdict(False, f"too_old:source:{src_age:.1f}m", src_age)

    if updated_ms is not None:
        upd_age = _age_minutes(updated_ms, now)
        if reject_reposts:
            if posted_ms is not None:
                posted_age = _age_minutes(posted_ms, now)
                return FreshnessVerdict(
                    False,
                    f"repost:posted:{posted_age:.1f}m",
                    upd_age,
                )
            return FreshnessVerdict(False, "repost:no_posted_date", upd_age)
        if _ok(upd_age) and _repost_ok():
            return FreshnessVerdict(True, f"fresh:updated:{upd_age:.1f}m", upd_age)
        if _ok(upd_age) and not _repost_ok() and posted_ms is not None:
            return FreshnessVerdict(
                False,
                f"too_old:repost:{_age_minutes(posted_ms, now):.1f}m",
                upd_age,
            )

    if posted_ms is None and updated_ms is None:
        source = (job.source or "").lower()
        if reject_reposts and source in {"linkedin", "indeed", "google"}:
            return FreshnessVerdict(False, "missing_timestamp_linkedin")
        if require_timestamp:
            return FreshnessVerdict(False, "missing_timestamp")
        return FreshnessVerdict(True, "no_timestamp_allow")

    # Have timestamps but all too old
    if posted_ms is not None:
        age_min = _age_minutes(posted_ms, now)
        return FreshnessVerdict(False, f"too_old:source:{age_min:.1f}m", age_min)
    age_min = _age_minutes(updated_ms, now)  # type: ignore[arg-type]
    return FreshnessVerdict(False, f"too_old:updated:{age_min:.1f}m", age_min)
