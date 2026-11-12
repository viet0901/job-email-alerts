from __future__ import annotations

import json
import re
from typing import Any

import requests

from src.models import Job

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)
MINISITE_URL = "https://jobright.ai/minisites-jobs/newgrad/us/{category}?embed=true"
NEXT_DATA_RE = re.compile(
    r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>',
    re.DOTALL,
)


def fetch_category(category: str, timeout: int = 30) -> list[Job]:
    url = MINISITE_URL.format(category=category)
    resp = requests.get(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/xhtml+xml",
            "Referer": "https://www.newgrad-jobs.com/",
        },
        timeout=timeout,
    )
    resp.raise_for_status()
    match = NEXT_DATA_RE.search(resp.text)
    if not match:
        raise ValueError(f"__NEXT_DATA__ not found for category={category}")

    data: dict[str, Any] = json.loads(match.group(1))
    page_props = data.get("props", {}).get("pageProps", {})
    initial_jobs = page_props.get("initialJobs") or []
    jobs: list[Job] = []
    for item in initial_jobs:
        job = _parse_job(item, category=category)
        if job:
            jobs.append(job)
    return jobs


def fetch_all_categories(categories: list[str]) -> list[Job]:
    seen_ids: set[str] = set()
    all_jobs: list[Job] = []
    errors: list[str] = []
    for category in categories:
        try:
            for job in fetch_category(category):
                if job.id in seen_ids:
                    continue
                seen_ids.add(job.id)
                all_jobs.append(job)
        except Exception as exc:  # noqa: BLE001 — collect per-category failures
            errors.append(f"{category}: {exc}")
    if not all_jobs and errors:
        raise RuntimeError("All Jobright category fetches failed: " + "; ".join(errors))
    return all_jobs


def _parse_job(item: dict[str, Any], *, category: str) -> Job | None:
    job_id = str(item.get("id") or "").strip()
    title = (item.get("title") or "").strip()
    if not job_id or not title:
        return None
    apply_url = (item.get("applyUrl") or "").strip()
    if not apply_url:
        apply_url = f"https://jobright.ai/jobs/info/{job_id}"

    h1b = item.get("h1bSponsored")
    if h1b is not None:
        h1b = str(h1b).strip() or None

    posted = item.get("postedDate")
    posted_ms = int(posted) if isinstance(posted, (int, float)) else None

    return Job(
        id=job_id,
        title=title,
        company=(item.get("company") or "").strip(),
        location=(item.get("location") or "").strip(),
        work_model=(item.get("workModel") or "").strip(),
        apply_url=apply_url,
        qualifications=(item.get("qualifications") or "").strip(),
        h1b_sponsored=h1b,
        salary=(item.get("salary") or "").strip(),
        category=category,
        source="jobright",
        posted_date_ms=posted_ms,
        raw=item,
    )
