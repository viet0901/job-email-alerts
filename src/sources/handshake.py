"""Handshake public listings (city SEO pages + JobPosting JSON-LD).

Handshake's in-app feed is auth-walled for verified students. This scraper
only hits the public surface:

  https://joinhandshake.com/find-jobs/{city}-{state}
  https://app.joinhandshake.com/public/jobs/{id}

Coverage is a small slice of total Handshake postings, but it needs no login.
"""

from __future__ import annotations

import json
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from typing import Any

import requests

from src.models import Job

_BASE = "https://joinhandshake.com"
_CITY_URL = f"{_BASE}/find-jobs/{{slug}}"
_DETAIL_URL = "https://app.joinhandshake.com/public/jobs/{job_id}"
_TIMEOUT = 20
_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)

_JOB_ID_RE = re.compile(
    r"https://app\.joinhandshake\.com/public/jobs/(\d+)",
)
_LDJSON_RE = re.compile(
    r'<script[^>]+application/ld\+json[^>]*>(.*?)</script>',
    re.DOTALL | re.IGNORECASE,
)

# Default metros when config omits cities (Handshake SEO landing pages)
_DEFAULT_CITIES = [
    "new-york-ny",
    "san-francisco-ca",
    "san-jose-ca",
    "los-angeles-ca",
    "seattle-wa",
    "boston-ma",
    "austin-tx",
    "chicago-il",
    "washington-dc",
    "denver-co",
    "atlanta-ga",
    "remote",
]


def fetch_handshake_jobs(
    *,
    cities: list[str] | None = None,
    search_terms: list[str] | None = None,
    results_wanted: int = 40,
    hours_old: int | None = 72,
    detail_workers: int = 6,
) -> list[Job]:
    """
    Scrape public Handshake city pages, enrich via JSON-LD detail pages,
    then keep jobs whose title/description match any search_term.
    """
    session = requests.Session()
    session.headers.update({"User-Agent": _UA, "Accept-Language": "en-US,en;q=0.9"})

    slugs = _normalize_cities(cities) or list(_DEFAULT_CITIES)
    job_ids = _collect_job_ids(session, slugs)
    if not job_ids:
        return []

    # Fetch more details than we return so keyword filter still has enough
    fetch_n = min(len(job_ids), max(results_wanted * 4, results_wanted + 30))
    subset = job_ids[:fetch_n]

    details: dict[str, dict] = {}
    with ThreadPoolExecutor(max_workers=detail_workers) as pool:
        futures = {
            pool.submit(_fetch_detail, session, jid): jid for jid in subset
        }
        for fut in as_completed(futures):
            jid = futures[fut]
            data = fut.result()
            if data:
                details[jid] = data

    cutoff = None
    if hours_old and hours_old > 0:
        cutoff = datetime.now(timezone.utc) - timedelta(hours=hours_old)
    now = datetime.now(timezone.utc)
    terms = [t.strip().lower() for t in (search_terms or []) if t and t.strip()]

    jobs: list[Job] = []
    seen: set[str] = set()
    for jid in subset:
        data = details.get(jid)
        if not data:
            continue
        job = _to_job(jid, data, now=now, cutoff=cutoff, terms=terms)
        if not job or job.id in seen:
            continue
        seen.add(job.id)
        jobs.append(job)
        if len(jobs) >= results_wanted:
            break
    return jobs


def _normalize_cities(cities: list[str] | None) -> list[str]:
    if not cities:
        return []
    out: list[str] = []
    seen: set[str] = set()
    for raw in cities:
        slug = _city_slug(str(raw))
        if slug and slug not in seen:
            seen.add(slug)
            out.append(slug)
    return out


def _city_slug(location: str) -> str:
    """'New York, NY' / 'new-york-ny' → 'new-york-ny'."""
    text = location.strip().lower()
    if not text:
        return ""
    if re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)+", text):
        return text
    parts = [p.strip() for p in text.split(",") if p.strip()]
    city = re.sub(r"[^a-z0-9\s]", "", parts[0])
    city = re.sub(r"\s+", "-", city).strip("-")
    if len(parts) > 1:
        state = re.sub(r"[^a-z0-9]", "", parts[1])
        if state:
            return f"{city}-{state}"
    return city


def _collect_job_ids(session: requests.Session, slugs: list[str]) -> list[str]:
    ordered: list[str] = []
    seen: set[str] = set()
    for slug in slugs:
        url = _CITY_URL.format(slug=slug)
        try:
            resp = session.get(url, timeout=_TIMEOUT)
        except requests.RequestException as exc:
            print(f"  Handshake city {slug} failed: {exc}")
            continue
        if resp.status_code != 200:
            print(f"  Handshake city {slug} HTTP {resp.status_code}")
            continue
        for jid in _JOB_ID_RE.findall(resp.text):
            if jid not in seen:
                seen.add(jid)
                ordered.append(jid)
    return ordered


def _fetch_detail(session: requests.Session, job_id: str) -> dict | None:
    url = _DETAIL_URL.format(job_id=job_id)
    try:
        resp = session.get(url, timeout=_TIMEOUT)
    except requests.RequestException:
        return None
    if resp.status_code != 200:
        return None
    for blob in _LDJSON_RE.findall(resp.text):
        try:
            data = json.loads(blob)
        except (ValueError, TypeError):
            continue
        if isinstance(data, dict) and data.get("@type") == "JobPosting":
            return data
        if isinstance(data, list):
            for item in data:
                if isinstance(item, dict) and item.get("@type") == "JobPosting":
                    return item
    return None


def _to_job(
    job_id: str,
    data: dict[str, Any],
    *,
    now: datetime,
    cutoff: datetime | None,
    terms: list[str],
) -> Job | None:
    valid_through = _parse_iso(data.get("validThrough"))
    if valid_through is not None and valid_through < now:
        return None

    posted = _parse_iso(data.get("datePosted"))
    if cutoff and posted and posted < cutoff:
        return None

    title_raw = str(data.get("title") or "").strip()
    title = title_raw.split(" | ")[0].strip() if title_raw else ""
    if not title:
        return None

    desc_html = str(data.get("description") or "")
    description = re.sub(r"<[^>]+>", " ", desc_html)
    description = re.sub(r"\s+", " ", description).strip()
    if len(description) > 6000:
        description = description[:6000] + "…"

    blob = f"{title}\n{description}".lower()
    if terms and not _matches_terms(blob, terms):
        return None

    org = data.get("hiringOrganization") or {}
    company = ""
    if isinstance(org, dict):
        company = str(org.get("name") or "").strip()
    company = company or "Unknown"

    location = _format_location(data.get("jobLocation"))
    employment = data.get("employmentType")
    work_model = ""
    if isinstance(employment, str) and "remote" in employment.lower():
        work_model = "Remote"
    if "remote" in location.lower():
        work_model = "Remote"

    salary = _format_salary(data.get("baseSalary"))
    posted_ms = int(posted.timestamp() * 1000) if posted else None

    return Job(
        id=f"hs:{job_id}",
        title=title,
        company=company,
        location=location,
        work_model=work_model,
        apply_url=_DETAIL_URL.format(job_id=job_id),
        qualifications=description,
        h1b_sponsored=None,
        salary=salary,
        category="handshake",
        source="handshake",
        posted_date_ms=posted_ms,
        raw={
            "employmentType": employment,
            "industry": data.get("industry"),
            "datePosted": data.get("datePosted"),
        },
    )


def _matches_terms(blob: str, terms: list[str]) -> bool:
    """Keep if any search term appears, or all significant words of a term appear."""
    for term in terms:
        if term in blob:
            return True
        words = [w for w in re.split(r"\s+", term) if len(w) >= 3]
        if words and all(w in blob for w in words):
            return True
    return False


def _format_location(value: Any) -> str:
    if not value:
        return ""
    locs = value if isinstance(value, list) else [value]
    parts: list[str] = []
    for loc in locs:
        if not isinstance(loc, dict):
            continue
        addr = loc.get("address") or {}
        if not isinstance(addr, dict):
            continue
        city = str(addr.get("addressLocality") or "").strip()
        region = str(addr.get("addressRegion") or "").strip()
        country = addr.get("addressCountry")
        if isinstance(country, dict):
            country = country.get("name")
        country = str(country or "").strip()
        chunk = ", ".join(p for p in (city, region) if p)
        if country and country not in chunk:
            chunk = f"{chunk}, {country}" if chunk else country
        if chunk:
            parts.append(chunk)
    return "; ".join(parts)


def _format_salary(raw: Any) -> str:
    if not isinstance(raw, dict):
        return ""
    val = raw.get("value")
    if not isinstance(val, dict):
        return ""
    currency = raw.get("currency") or "USD"
    unit = str(val.get("unitText") or "YEAR").upper()
    mn, mx = val.get("minValue"), val.get("maxValue")
    single = val.get("value")
    if mn is not None and mx is not None:
        return f"{currency} {mn}-{mx}/{unit}"
    if single is not None:
        return f"{currency} {single}/{unit}"
    if mn is not None:
        return f"{currency} {mn}+/{unit}"
    if mx is not None:
        return f"{currency} up to {mx}/{unit}"
    return ""


def _parse_iso(value: Any) -> datetime | None:
    if not value or not isinstance(value, str):
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except ValueError:
        return None
