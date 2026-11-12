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
API_URL = "https://api.lever.co/v0/postings/{token}?mode=json"


def fetch_board(token: str, company_name: str | None = None, timeout: int = 25) -> list[Job]:
    """Fetch published jobs from a Lever public board token."""
    url = API_URL.format(token=token)
    resp = requests.get(
        url,
        headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
        timeout=timeout,
    )
    resp.raise_for_status()
    payload = resp.json()
    if not isinstance(payload, list):
        return []
    company = (company_name or token).strip()
    jobs: list[Job] = []
    for item in payload:
        job = _parse_job(item, token=token, company=company)
        if job:
            jobs.append(job)
    return jobs


def fetch_all_boards(
    boards: list[dict[str, Any] | str],
    *,
    workers: int = 10,
) -> list[Job]:
    """
    boards example:
      - {token: netflix, name: Netflix}
      - netflix
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
        raise RuntimeError("All Lever board fetches failed: " + "; ".join(errors))
    if errors:
        print(f"  Lever partial errors ({len(errors)}): {errors[:3]}")
    return all_jobs


def _parse_job(item: dict[str, Any], *, token: str, company: str) -> Job | None:
    raw_id = item.get("id") or item.get("id")
    title = str(item.get("text") or "").strip()
    if not title or not raw_id:
        return None

    categories = item.get("categories") or {}
    location = ""
    if isinstance(categories, dict):
        location = str(categories.get("location") or categories.get("allLocations") or "")
        if isinstance(location, list):
            location = ", ".join(str(x) for x in location)

    apply_url = str(item.get("hostedUrl") or item.get("applyUrl") or "").strip()
    description = str(item.get("descriptionPlain") or item.get("description") or "").strip()
    lists = item.get("lists") or []
    if isinstance(lists, list):
        extra = []
        for block in lists:
            if not isinstance(block, dict):
                continue
            heading = str(block.get("text") or "").strip()
            content = str(block.get("content") or "").strip()
            if heading or content:
                extra.append(f"{heading}\n{content}".strip())
        if extra:
            description = (description + "\n\n" + "\n\n".join(extra)).strip()
    if len(description) > 8000:
        description = description[:8000] + "…"

    work_model = ""
    workplace = str(item.get("workplaceType") or "").lower()
    if "remote" in workplace:
        work_model = "Remote"
    elif "hybrid" in workplace:
        work_model = "Hybrid"

    posted_ms = None
    created = item.get("createdAt")
    if isinstance(created, (int, float)):
        # Lever uses epoch ms
        posted_ms = int(created) if created > 1e12 else int(created * 1000)
    elif isinstance(created, str) and created.strip():
        try:
            dt = datetime.fromisoformat(created.replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            posted_ms = int(dt.timestamp() * 1000)
        except ValueError:
            posted_ms = None

    return Job(
        id=f"lever:{token}:{raw_id}",
        title=title,
        company=company,
        location=str(location or "").strip(),
        work_model=work_model,
        apply_url=apply_url,
        qualifications=description,
        h1b_sponsored=None,
        salary="",
        category="",
        source="lever",
        posted_date_ms=posted_ms,
        updated_date_ms=posted_ms,
        raw=item,
    )
