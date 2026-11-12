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
API_URL = "https://api.smartrecruiters.com/v1/companies/{token}/postings"


def fetch_board(
    token: str,
    company_name: str | None = None,
    *,
    query: str | None = None,
    country: str | None = "us",
    limit: int = 100,
    timeout: int = 25,
) -> list[Job]:
    """Fetch published jobs from a SmartRecruiters public company board."""
    company = (company_name or token).strip()
    jobs: list[Job] = []
    offset = 0
    page_size = min(100, max(1, limit))
    while offset < limit:
        params: dict[str, Any] = {"limit": page_size, "offset": offset}
        if query:
            params["q"] = query
        if country:
            params["country"] = country
        resp = requests.get(
            API_URL.format(token=token),
            headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
            params=params,
            timeout=timeout,
        )
        resp.raise_for_status()
        payload = resp.json() or {}
        content = payload.get("content") or []
        if not content:
            break
        for item in content:
            job = _parse_job(item, token=token, company=company)
            if job:
                jobs.append(job)
        total = int(payload.get("totalFound") or 0)
        offset += len(content)
        if offset >= total or len(content) < page_size:
            break
    return jobs


def fetch_all_boards(
    boards: list[dict[str, Any] | str],
    *,
    workers: int = 6,
) -> list[Job]:
    specs: list[tuple[str, str, str | None, int, str | None]] = []
    for entry in boards or []:
        if isinstance(entry, str):
            token, name, query, limit, country = entry, entry, None, 100, "us"
        else:
            token = str(entry.get("token") or "").strip()
            name = str(entry.get("name") or token).strip()
            query = entry.get("query")
            limit = int(entry.get("limit") or 100)
            country = entry.get("country", "us")
        if token:
            specs.append((token, name, query, limit, country))
    if not specs:
        return []

    errors: list[str] = []
    batches: list[list[Job]] = []

    def _one(spec: tuple[str, str, str | None, int, str | None]) -> list[Job]:
        token, name, query, limit, country = spec
        return fetch_board(
            token,
            company_name=name,
            query=query,
            country=country,
            limit=limit,
        )

    workers = max(1, min(workers, len(specs)))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futs = {pool.submit(_one, spec): spec[0] for spec in specs}
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
        raise RuntimeError("All SmartRecruiters fetches failed: " + "; ".join(errors))
    if errors:
        print(f"  SmartRecruiters partial errors ({len(errors)}): {errors[:3]}")
    return all_jobs


def _parse_job(item: dict[str, Any], *, token: str, company: str) -> Job | None:
    raw_id = item.get("id") or item.get("uuid") or item.get("refNumber")
    title = str(item.get("name") or item.get("title") or "").strip()
    if not title or not raw_id:
        return None

    location = ""
    loc = item.get("location") or {}
    if isinstance(loc, dict):
        parts = [
            str(loc.get("city") or "").strip(),
            str(loc.get("region") or "").strip(),
            str(loc.get("country") or "").strip(),
        ]
        location = ", ".join(p for p in parts if p)
    elif isinstance(loc, str):
        location = loc.strip()

    apply_url = str(
        item.get("applyUrl")
        or item.get("jobAdUrl")
        or item.get("ref")
        or f"https://jobs.smartrecruiters.com/{token}/{raw_id}"
    ).strip()

    description = str(
        item.get("jobAd", {}).get("sections", {}).get("jobDescription", {}).get("text")
        if isinstance(item.get("jobAd"), dict)
        else ""
    )
    if not description:
        description = str(item.get("description") or item.get("jobDescription") or "")

    posted_ms = _parse_iso(item.get("releasedDate") or item.get("createdOn"))
    if len(description) > 8000:
        description = description[:8000] + "…"

    return Job(
        id=f"sr:{token}:{raw_id}",
        title=title,
        company=company,
        location=location,
        work_model="",
        apply_url=apply_url,
        qualifications=description,
        h1b_sponsored=None,
        salary="",
        category=str(item.get("function") or item.get("department") or ""),
        source="smartrecruiters",
        posted_date_ms=posted_ms,
        updated_date_ms=posted_ms,
        raw=item,
    )


def _parse_iso(value: Any) -> int | None:
    if not value:
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
