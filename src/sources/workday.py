from __future__ import annotations

import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from html import unescape
from typing import Any

import requests

from src.models import Job
from src.filters.location import location_text_status

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)
TAG_RE = re.compile(r"<[^>]+>")
WS_RE = re.compile(r"\s+")

# Only pull JD detail for list hits that look relevant (keeps multi-board runs fast).
DEFAULT_TITLE_HINTS = (
    "data scientist",
    "data analyst",
    "data science",
    "machine learning",
    "ai engineer",
    "ml engineer",
    "business intelligence",
    "bi analyst",
    "llm",
    "generative ai",
    "rag engineer",
    "analytics engineer",
    "data analytics",
    "quantitative analyst",
    "quantitative",
    "quant analyst",
)


def _strip_html(html: str) -> str:
    text = TAG_RE.sub(" ", html or "")
    text = unescape(text)
    return WS_RE.sub(" ", text).strip()


def _title_interesting(title: str, hints: tuple[str, ...] | list[str]) -> bool:
    low = (title or "").lower()
    if not low:
        return False
    return any(h in low for h in hints)


def _session() -> requests.Session:
    s = requests.Session()
    s.headers.update(
        {
            "User-Agent": USER_AGENT,
            "Accept": "application/json",
            "Content-Type": "application/json",
        }
    )
    return s


def fetch_board(
    *,
    host: str,
    tenant: str,
    site: str,
    company_name: str,
    search_terms: list[str] | None = None,
    limit: int = 25,
    timeout: int = 20,
    title_hints: list[str] | None = None,
    detail_workers: int = 6,
    us_only: bool = True,
) -> list[Job]:
    """
    Fetch jobs from a Workday public career site via CXS JSON API.

    Example:
      host=mastercard.wd1.myworkdayjobs.com
      tenant=mastercard
      site=CorporateCareers
    """
    host = host.strip().removeprefix("https://").removeprefix("http://").rstrip("/")
    tenant = tenant.strip()
    site = site.strip()
    company = (company_name or tenant).strip()
    base = f"https://{host}/wday/cxs/{tenant}/{site}"

    terms = [t.strip() for t in (search_terms or [""]) if t is not None]
    if not terms:
        terms = [""]
    hints = tuple(h.lower() for h in (title_hints or DEFAULT_TITLE_HINTS) if h)

    session = _session()
    seen: set[str] = set()
    candidates: list[dict[str, Any]] = []

    for term in terms:
        if len(candidates) >= limit:
            break
        offset = 0
        # Scan at most a couple pages per term — searchText already narrows.
        max_scan = min(40, limit * 2)
        while offset < max_scan and len(candidates) < limit:
            page = min(20, max_scan - offset)
            payload = {
                "appliedFacets": {},
                "limit": page,
                "offset": offset,
                "searchText": term,
            }
            try:
                resp = session.post(f"{base}/jobs", json=payload, timeout=timeout)
                resp.raise_for_status()
                data = resp.json() or {}
            except Exception:  # noqa: BLE001
                break

            postings = data.get("jobPostings") or []
            if not postings:
                break

            for item in postings:
                path = str(item.get("externalPath") or "").strip()
                if not path or path in seen:
                    continue
                title = str(item.get("title") or "").strip()
                if hints and not _title_interesting(title, hints):
                    continue
                loc_text = str(item.get("locationsText") or "").strip()
                if us_only and location_text_status(loc_text) == "non_us":
                    continue
                seen.add(path)
                candidates.append(item)
                if len(candidates) >= limit:
                    break

            offset += len(postings)
            total = int(data.get("total") or 0)
            if offset >= total or len(postings) < page:
                break

    if not candidates:
        return []

    jobs: list[Job] = []
    workers = max(1, min(detail_workers, len(candidates)))

    def _one(item: dict[str, Any]) -> Job | None:
        path = str(item.get("externalPath") or "").strip()
        return _fetch_detail(
            session=session,
            base=base,
            path=path,
            list_item=item,
            company=company,
            timeout=timeout,
            host=host,
            site=site,
            us_only=us_only,
        )

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futs = [pool.submit(_one, item) for item in candidates]
        for fut in as_completed(futs):
            try:
                job = fut.result()
            except Exception:  # noqa: BLE001
                continue
            if job:
                jobs.append(job)
    return jobs


def fetch_all_boards(
    boards: list[dict[str, Any]],
    *,
    default_search_terms: list[str] | None = None,
    default_limit: int = 25,
    board_workers: int = 4,
) -> list[Job]:
    entries: list[dict[str, Any]] = [
        e for e in (boards or []) if isinstance(e, dict)
    ]
    if not entries:
        return []

    errors: list[str] = []
    batches: list[list[Job]] = []

    def _board(entry: dict[str, Any]) -> list[Job]:
        host = str(entry.get("host") or "").strip()
        tenant = str(entry.get("tenant") or "").strip()
        site = str(entry.get("site") or "").strip()
        name = str(entry.get("name") or tenant).strip()
        if not (host and tenant and site):
            return []
        return fetch_board(
            host=host,
            tenant=tenant,
            site=site,
            company_name=name,
            search_terms=entry.get("search_terms") or default_search_terms,
            limit=int(entry.get("limit") or default_limit),
            title_hints=entry.get("title_hints"),
            us_only=bool(entry.get("us_only", True)),
        )

    workers = max(1, min(board_workers, len(entries)))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futs = {pool.submit(_board, e): e for e in entries}
        for fut in as_completed(futs):
            entry = futs[fut]
            name = str(entry.get("name") or entry.get("tenant") or "?")
            try:
                batches.append(fut.result())
            except Exception as exc:  # noqa: BLE001
                errors.append(f"{name}: {exc}")

    seen: set[str] = set()
    all_jobs: list[Job] = []
    for batch in batches:
        for job in batch:
            if job.id in seen:
                continue
            seen.add(job.id)
            all_jobs.append(job)

    if not all_jobs and errors:
        raise RuntimeError("All Workday fetches failed: " + "; ".join(errors))
    if errors:
        print(f"  Workday partial errors ({len(errors)}): {errors[:3]}")
    return all_jobs


def _fetch_detail(
    *,
    session: requests.Session,
    base: str,
    path: str,
    list_item: dict[str, Any],
    company: str,
    timeout: int,
    host: str,
    site: str,
    us_only: bool = True,
) -> Job | None:
    title = str(list_item.get("title") or "").strip()
    location = str(list_item.get("locationsText") or "").strip()
    apply_url = f"https://{host}/{site}{path}"
    posted_ms = _parse_posted(list_item.get("postedOn") or list_item.get("bulletinStartDate"))
    description = ""
    country_name = ""
    country_code = ""

    try:
        resp = session.get(f"{base}{path}", timeout=timeout)
        if resp.ok:
            info = (resp.json() or {}).get("jobPostingInfo") or {}
            title = str(info.get("title") or title).strip()
            location = str(info.get("location") or location).strip()
            extra = info.get("additionalLocations") or []
            if isinstance(extra, list) and extra:
                extra_s = ", ".join(str(x) for x in extra if x)
                if extra_s and extra_s not in location:
                    location = f"{location}; {extra_s}" if location else extra_s
            country_name, country_code = _country_from_info(info)
            if country_name and country_name.lower() not in location.lower():
                location = f"{location}, {country_name}" if location else country_name
            description = _strip_html(str(info.get("jobDescription") or ""))
            posted_ms = _parse_posted(info.get("startDate")) or posted_ms
            if info.get("externalUrl"):
                apply_url = str(info["externalUrl"]).strip()
    except Exception:  # noqa: BLE001
        pass

    if not title:
        return None
    if us_only:
        if country_code and country_code.upper() != "US":
            return None
        if country_name:
            low = country_name.lower()
            if low not in {"united states", "united states of america", "usa", "us"}:
                return None
        elif location_text_status(location) == "non_us":
            return None
    if len(description) > 8000:
        description = description[:8000] + "…"

    raw_id = path.rstrip("/").split("/")[-1] or path
    return Job(
        id=f"wd:{company.lower().replace(' ', '-')}:{raw_id}",
        title=title,
        company=company,
        location=location,
        work_model="",
        apply_url=apply_url,
        qualifications=description,
        h1b_sponsored=None,
        salary="",
        category="",
        source="workday",
        posted_date_ms=posted_ms,
        updated_date_ms=posted_ms,
        raw=list_item,
    )


def _country_from_info(info: dict[str, Any]) -> tuple[str, str]:
    name = ""
    code = ""
    country = info.get("country")
    if isinstance(country, dict):
        name = str(country.get("descriptor") or "").strip()
    req = info.get("jobRequisitionLocation")
    if isinstance(req, dict):
        nested = req.get("country")
        if isinstance(nested, dict):
            name = name or str(nested.get("descriptor") or "").strip()
            code = str(nested.get("alpha2Code") or "").strip()
    return name, code


def _parse_posted(value: Any) -> int | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    # Workday often returns ISO dates like 2026-08-06
    for fmt in ("%Y-%m-%d", "%Y-%m-%dT%H:%M:%S.%f%z", "%Y-%m-%dT%H:%M:%S%z"):
        try:
            dt = datetime.strptime(text.replace("Z", "+0000"), fmt)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return int(dt.timestamp() * 1000)
        except ValueError:
            continue
    try:
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return int(dt.timestamp() * 1000)
    except ValueError:
        return None
