from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from typing import Any

import requests

from src.models import Job

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)
API_URL = "https://api.ashbyhq.com/posting-api/job-board/{token}"


def fetch_board(token: str, company_name: str | None = None, timeout: int = 25) -> list[Job]:
    """Fetch published jobs from an Ashby public job board token."""
    url = API_URL.format(token=token)
    resp = requests.get(
        url,
        headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
        timeout=timeout,
    )
    resp.raise_for_status()
    payload = resp.json() or {}
    jobs_raw = payload.get("jobs") or []
    company = (company_name or token).strip()
    jobs: list[Job] = []
    for item in jobs_raw:
        job = _parse_job(item, token=token, company=company)
        if job:
            jobs.append(job)
    return jobs


def fetch_all_boards(
    boards: list[dict[str, Any] | str],
    *,
    workers: int = 10,
) -> list[Job]:
    entries: list[tuple[str, str]] = []
    for entry in boards or []:
        if isinstance(entry, str):
            token, name = entry, entry
        else:
            token = str(entry.get("token") or "").strip()
            name = str(entry.get("name") or token).strip()
        if token:
            entries.append((token, name))
    if not entries:
        return []

    errors: list[str] = []
    batches: list[list[Job]] = []
    workers = max(1, min(workers, len(entries)))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futs = {pool.submit(fetch_board, token, name): token for token, name in entries}
        for fut in as_completed(futs):
            token = futs[fut]
            try:
                batches.append(fut.result())
            except Exception as exc:  # noqa: BLE001
                errors.append(f"{token}: {exc}")

    seen: set[str] = set()
    all_jobs: list[Job] = []
    for batch in batches:
        for job in batch:
            if job.id in seen:
                continue
            seen.add(job.id)
            all_jobs.append(job)
    if not all_jobs and errors:
        raise RuntimeError("All Ashby board fetches failed: " + "; ".join(errors))
    if errors:
        print(f"  Ashby partial errors ({len(errors)}): {errors[:3]}")
    return all_jobs


def _parse_job(item: dict[str, Any], *, token: str, company: str) -> Job | None:
    raw_id = item.get("id") or item.get("jobId") or item.get("jobUrl")
    title = str(item.get("title") or "").strip()
    if not title or not raw_id:
        return None

    location = str(item.get("location") or "").strip()
    locations = item.get("address") or item.get("locations")
    if not location and isinstance(locations, dict):
        location = str(locations.get("postalAddress") or locations.get("addressLocality") or "")
    if not location and isinstance(locations, list):
        location = ", ".join(str(x) for x in locations if x)

    apply_url = str(
        item.get("jobUrl") or item.get("applyUrl") or item.get("externalLink") or ""
    ).strip()
    description = str(
        item.get("descriptionPlain")
        or item.get("descriptionHtml")
        or item.get("description")
        or ""
    ).strip()
    if len(description) > 8000:
        description = description[:8000] + "…"

    work_model = ""
    workplace = str(item.get("workplaceType") or item.get("isRemote") or "").lower()
    if workplace in {"true", "1"} or "remote" in workplace:
        work_model = "Remote"
    elif "hybrid" in workplace:
        work_model = "Hybrid"

    posted_ms = _parse_ts(item.get("publishedAt") or item.get("updatedAt"))
    updated_ms = _parse_ts(item.get("updatedAt") or item.get("publishedAt"))

    return Job(
        id=f"ashby:{token}:{raw_id}",
        title=title,
        company=company,
        location=location,
        work_model=work_model,
        apply_url=apply_url,
        qualifications=description,
        h1b_sponsored=None,
        salary="",
        category="",
        source="ashby",
        posted_date_ms=posted_ms,
        updated_date_ms=updated_ms,
        raw=item,
    )


def _parse_ts(value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        num = float(value)
        if num > 1e12:
            return int(num)
        if num > 1e9:
            return int(num * 1000)
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return int(dt.timestamp() * 1000)
    except ValueError:
        return None
