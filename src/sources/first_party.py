"""Official large-company career sites (not LinkedIn/Indeed aggregators)."""

from __future__ import annotations

import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from html import unescape
from typing import Any

import requests

from src.models import Job

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)
HEADERS = {"User-Agent": USER_AGENT, "Accept": "application/json"}
_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")


def _strip_html(text: str) -> str:
    cleaned = _TAG_RE.sub(" ", text or "")
    return _WS_RE.sub(" ", unescape(cleaned)).strip()


def _session() -> requests.Session:
    s = requests.Session()
    s.headers.update(HEADERS)
    return s


def _iso_ms(value: Any) -> int | None:
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
    if not text or text.lower() in {"nan", "none", "null"}:
        return None
    if text.isdigit():
        return _iso_ms(int(text))
    for fmt in (
        "%Y-%m-%d",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%dT%H:%M:%SZ",
        "%Y-%m-%dT%H:%M:%S.%fZ",
        "%B %d, %Y",
        "%b %d, %Y",
        "%m/%d/%Y",
    ):
        try:
            dt = datetime.strptime(text.replace("Z", ""), fmt.replace("Z", ""))
            return int(dt.replace(tzinfo=timezone.utc).timestamp() * 1000)
        except ValueError:
            continue
    try:
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return int(dt.timestamp() * 1000)
    except ValueError:
        return None


def fetch_amazon_jobs(
    *,
    search_terms: list[str] | None = None,
    country: str = "USA",
    limit_per_term: int = 50,
    timeout: int = 25,
) -> list[Job]:
    """amazon.jobs public search.json — first-party Amazon career site."""
    terms = [t.strip() for t in (search_terms or ["Data Scientist"]) if t and str(t).strip()]
    session = _session()
    seen: set[str] = set()
    out: list[Job] = []
    for term in terms:
        offset = 0
        while offset < limit_per_term:
            page = min(100, limit_per_term - offset)
            resp = session.get(
                "https://www.amazon.jobs/en/search.json",
                params={
                    "base_query": term,
                    "offset": offset,
                    "result_limit": page,
                    "country": country,
                    "sort": "recent",
                },
                timeout=timeout,
            )
            resp.raise_for_status()
            payload = resp.json() or {}
            jobs = payload.get("jobs") or []
            if not jobs:
                break
            for item in jobs:
                job = _amazon_job(item)
                if not job or job.id in seen:
                    continue
                seen.add(job.id)
                out.append(job)
            offset += len(jobs)
            hits = int(payload.get("hits") or 0)
            if offset >= hits or len(jobs) < page:
                break
    return out


def _amazon_job(item: dict[str, Any]) -> Job | None:
    title = str(item.get("title") or "").strip()
    raw_id = str(item.get("id_icims") or item.get("id") or "").strip()
    if not title or not raw_id:
        return None
    path = str(item.get("job_path") or item.get("url_next_step") or "").strip()
    apply_url = path if path.startswith("http") else f"https://www.amazon.jobs{path}"
    loc_parts = [
        str(item.get("city") or "").strip(),
        str(item.get("state") or "").strip(),
        str(item.get("country_code") or "").strip(),
    ]
    location = ", ".join(p for p in loc_parts if p) or str(
        item.get("location") or item.get("normalized_location") or ""
    )
    sections = []
    for label, key in (
        ("Description", "description"),
        ("Basic Qualifications", "basic_qualifications"),
        ("Preferred Qualifications", "preferred_qualifications"),
    ):
        val = _strip_html(str(item.get(key) or ""))
        if val:
            sections.append(f"{label}: {val}")
    if not sections:
        short = _strip_html(str(item.get("description_short") or ""))
        if short:
            sections.append(short)
    desc = "\n\n".join(sections)
    if len(desc) > 10000:
        desc = desc[:10000] + "…"
    posted = _iso_ms(
        item.get("posted_date")
        or item.get("posted_utc_date_time")
        or item.get("updated_time")
    )
    company = str(item.get("company_name") or "Amazon").strip() or "Amazon"
    return Job(
        id=f"amzn:{raw_id}",
        title=title,
        company=company,
        location=location,
        work_model="Remote" if "virtual" in location.lower() else "",
        apply_url=apply_url,
        qualifications=desc,
        source="amazon",
        posted_date_ms=posted,
        updated_date_ms=posted,
        raw=item,
    )


def fetch_netflix_jobs(
    *,
    search_terms: list[str] | None = None,
    location: str = "United States",
    limit_per_term: int = 40,
    timeout: int = 25,
) -> list[Job]:
    """Netflix careers via Eightfold public apply API (plus detail fetch for JDs)."""
    terms = [t.strip() for t in (search_terms or ["Data Scientist"]) if t and str(t).strip()]
    session = _session()
    seen: set[str] = set()
    items: list[dict[str, Any]] = []
    for term in terms:
        resp = session.get(
            "https://explore.jobs.netflix.net/api/apply/v2/jobs",
            params={
                "domain": "netflix.com",
                "query": term,
                "location": location,
                "start": 0,
                "num": min(50, limit_per_term),
            },
            timeout=timeout,
        )
        resp.raise_for_status()
        payload = resp.json() or {}
        for item in payload.get("positions") or []:
            raw_id = str(item.get("id") or item.get("ats_job_id") or "").strip()
            if not raw_id or raw_id in seen:
                continue
            seen.add(raw_id)
            items.append(item)

    if not items:
        return []

    def _enrich_and_parse(item: dict[str, Any]) -> Job | None:
        raw_id = str(item.get("id") or "").strip()
        if raw_id and not item.get("job_description"):
            try:
                detail = session.get(
                    f"https://explore.jobs.netflix.net/api/apply/v2/jobs/{raw_id}",
                    params={"domain": "netflix.com"},
                    timeout=timeout,
                )
                if detail.ok:
                    data = detail.json() or {}
                    if data.get("job_description"):
                        item = {**item, "job_description": data.get("job_description")}
            except Exception:  # noqa: BLE001
                pass
        return _eightfold_job(item, company="Netflix", prefix="nflx")

    out: list[Job] = []
    with ThreadPoolExecutor(max_workers=min(8, len(items))) as pool:
        for job in pool.map(_enrich_and_parse, items):
            if job:
                out.append(job)
    return out


def _eightfold_job(item: dict[str, Any], *, company: str, prefix: str) -> Job | None:
    title = str(item.get("name") or item.get("posting_name") or "").strip()
    raw_id = str(item.get("id") or item.get("ats_job_id") or "").strip()
    if not title or not raw_id:
        return None
    loc = item.get("location") or item.get("locations") or ""
    if isinstance(loc, list):
        loc = ", ".join(str(x) for x in loc if x)
    desc = _strip_html(str(item.get("job_description") or ""))
    if len(desc) > 10000:
        desc = desc[:10000] + "…"
    posted = _iso_ms(item.get("t_create") or item.get("t_update"))
    apply_url = (
        f"https://explore.jobs.netflix.net/careers/job/{raw_id}"
        if prefix == "nflx"
        else str(item.get("canonicalPositionUrl") or "")
    )
    return Job(
        id=f"{prefix}:{raw_id}",
        title=title,
        company=company,
        location=str(loc),
        apply_url=apply_url,
        qualifications=desc,
        source=company.lower(),
        posted_date_ms=posted,
        updated_date_ms=_iso_ms(item.get("t_update")) or posted,
        raw=item,
    )


def fetch_microsoft_jobs(
    *,
    search_terms: list[str] | None = None,
    limit_per_term: int = 40,
    timeout: int = 25,
) -> list[Job]:
    """Microsoft careers search API (Eightfold/GCSS)."""
    terms = [t.strip() for t in (search_terms or ["Data Scientist"]) if t and str(t).strip()]
    session = _session()
    seen: set[str] = set()
    out: list[Job] = []
    url = "https://gcsservices.careers.microsoft.com/search/api/v1/search"
    errors: list[str] = []
    for term in terms:
        try:
            resp = session.get(
                url,
                params={
                    "q": term,
                    "l": "en_us",
                    "pg": 1,
                    "pgSz": min(20, limit_per_term),
                    "o": "Recent",
                    "flt": "true",
                },
                timeout=timeout,
            )
            resp.raise_for_status()
            payload = resp.json() or {}
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{term}: {exc}")
            continue
        jobs = (
            ((payload.get("operationResult") or {}).get("result") or {}).get("jobs")
            or payload.get("jobs")
            or []
        )
        for item in jobs:
            job = _microsoft_job(item)
            if not job or job.id in seen:
                continue
            seen.add(job.id)
            out.append(job)
    if not out and errors:
        raise RuntimeError("Microsoft careers API failed: " + errors[0])
    return out


def _microsoft_job(item: dict[str, Any]) -> Job | None:
    title = str(item.get("title") or item.get("jobTitle") or "").strip()
    raw_id = str(item.get("jobId") or item.get("id") or "").strip()
    if not title or not raw_id:
        return None
    props = item.get("properties") or {}
    location = str(
        props.get("primaryLocation")
        or item.get("location")
        or item.get("primaryLocation")
        or ""
    )
    desc = _strip_html(str(props.get("description") or item.get("description") or ""))
    if len(desc) > 10000:
        desc = desc[:10000] + "…"
    posted = _iso_ms(
        item.get("postingDate") or item.get("postedDate") or props.get("postedDate")
    )
    apply_url = (
        str(item.get("jobUrl") or "").strip()
        or f"https://jobs.careers.microsoft.com/global/en/job/{raw_id}"
    )
    return Job(
        id=f"msft:{raw_id}",
        title=title,
        company=company if (company := "Microsoft") else "Microsoft",
        location=location,
        apply_url=apply_url,
        qualifications=desc,
        source="microsoft",
        posted_date_ms=posted,
        updated_date_ms=posted,
        raw=item,
    )


def fetch_all_first_party(cfg: dict[str, Any] | None) -> list[Job]:
    """Pull Amazon / Netflix / Microsoft career sites when enabled."""
    cfg = cfg or {}
    if not cfg.get("enabled", True):
        return []
    terms = list(cfg.get("search_terms") or ["Data Scientist", "Data Analyst", "Machine Learning"])
    limit = int(cfg.get("limit_per_term") or 40)
    jobs: list[Job] = []
    errors: list[str] = []

    sources = (
        (
            "amazon",
            lambda: fetch_amazon_jobs(
                search_terms=terms,
                country=str(cfg.get("amazon_country") or "USA"),
                limit_per_term=limit,
            ),
        ),
        (
            "netflix",
            lambda: fetch_netflix_jobs(search_terms=terms, limit_per_term=limit),
        ),
        (
            "microsoft",
            lambda: fetch_microsoft_jobs(search_terms=terms, limit_per_term=limit),
        ),
    )
    enabled = cfg.get("sites") or ["amazon", "netflix", "microsoft"]
    selected = [(name, fn) for name, fn in sources if name in enabled]
    if not selected:
        return []
    with ThreadPoolExecutor(max_workers=len(selected)) as pool:
        futs = {pool.submit(fn): name for name, fn in selected}
        for fut in as_completed(futs):
            name = futs[fut]
            try:
                batch = fut.result()
                jobs.extend(batch)
                print(f"  First-party {name}: {len(batch)} jobs")
            except Exception as exc:  # noqa: BLE001
                errors.append(f"{name}: {exc}")
                print(f"  First-party {name} failed: {exc}")
    if errors and not jobs:
        raise RuntimeError("All first-party career fetches failed: " + "; ".join(errors))
    return jobs
