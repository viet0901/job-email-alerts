from __future__ import annotations

import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from html import unescape
from typing import Any

import requests

from src.models import Job

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)
API_URL = "https://boards-api.greenhouse.io/v1/boards/{token}/jobs?content=true"

TAG_RE = re.compile(r"<[^>]+>")
WS_RE = re.compile(r"\s+")


def _strip_html(html: str) -> str:
    text = TAG_RE.sub(" ", html or "")
    text = unescape(text)
    return WS_RE.sub(" ", text).strip()


def fetch_board(token: str, company_name: str | None = None, timeout: int = 25) -> list[Job]:
    """Fetch published jobs from a Greenhouse public board token."""
    url = API_URL.format(token=token)
    resp = requests.get(
        url,
        headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
        timeout=timeout,
    )
    resp.raise_for_status()
    payload: dict[str, Any] = resp.json()
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
    workers: int = 12,
) -> list[Job]:
    """
    boards example:
      - {token: stripe, name: Stripe}
      - stripe   # shorthand string token
    """
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
        raise RuntimeError("All Greenhouse board fetches failed: " + "; ".join(errors))
    if errors:
        print(f"  Greenhouse partial errors ({len(errors)}): {errors[:3]}")
    return all_jobs


def _parse_job(item: dict[str, Any], *, token: str, company: str) -> Job | None:
    raw_id = item.get("id")
    title = (item.get("title") or "").strip()
    if raw_id is None or not title:
        return None

    loc_obj = item.get("location") or {}
    location = ""
    if isinstance(loc_obj, dict):
        location = (loc_obj.get("name") or "").strip()
    elif isinstance(loc_obj, str):
        location = loc_obj.strip()

    absolute_url = (item.get("absolute_url") or "").strip()
    content = _strip_html(item.get("content") or "")
    # Keep description bounded for LLM cost
    if len(content) > 6000:
        content = content[:6000] + "…"

    # True publish time = earliest of first_published / published_at / created_at.
    # updated_at is tracked separately — Greenhouse bumps it on edits/reposts.
    publish_candidates: list[float] = []
    updated_ms: int | None = None
    for key in ("first_published", "published_at", "created_at"):
        raw = item.get(key)
        if not isinstance(raw, str) or not raw:
            continue
        try:
            from datetime import datetime

            dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
            publish_candidates.append(dt.timestamp() * 1000)
        except ValueError:
            continue
    raw_updated = item.get("updated_at")
    if isinstance(raw_updated, str) and raw_updated:
        try:
            from datetime import datetime

            dt = datetime.fromisoformat(raw_updated.replace("Z", "+00:00"))
            updated_ms = int(dt.timestamp() * 1000)
        except ValueError:
            updated_ms = None
    posted_ms = int(min(publish_candidates)) if publish_candidates else updated_ms

    return Job(
        id=f"gh:{token}:{raw_id}",
        title=title,
        company=company,
        location=location,
        work_model="",
        apply_url=absolute_url or f"https://boards.greenhouse.io/{token}/jobs/{raw_id}",
        qualifications=content,
        h1b_sponsored=None,
        salary="",
        category=token,
        source="greenhouse",
        posted_date_ms=posted_ms,
        updated_date_ms=updated_ms,
        raw=item,
    )
