"""Cross-source job dedupe (LinkedIn vs Greenhouse vs Lever, etc.)."""

from __future__ import annotations

import re

from src.models import Job

_SOURCE_RANK = {
    "greenhouse": 0,
    "lever": 1,
    "ashby": 2,
    "workday": 3,
    "smartrecruiters": 4,
    "linkedin": 8,
    "indeed": 9,
    "google": 10,
    "handshake": 11,
    "jobright": 12,
    "github": 13,
}

_COMPANY_NOISE = re.compile(
    r"\b(inc\.?|llc|ltd\.?|corp\.?|corporation|company|co\.?|the)\b",
    re.I,
)
_TITLE_LOCATION_NOISE = re.compile(
    r"\b("
    r"remote|hybrid|onsite|on[\s-]?site|in[\s-]?office|"
    r"united\s+states|usa|\bus\b|u\.s\.a?\.?|"
    r"new\s+york(?:\s+city)?|nyc|sf|san\s+francisco|bay\s+area|"
    r"los\s+angeles|\bla\b|seattle|boston|austin|chicago|denver|"
    r"washington(?:\s+d\.?c\.?)?|atlanta|dallas|miami|"
    r"full[\s-]?time|part[\s-]?time"
    r")\b",
    re.I,
)


def _alnum(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", text.lower())


def job_fingerprint(job: Job) -> str:
    """Stable key for the same posting across ATS / LinkedIn / Handshake."""
    company = _COMPANY_NOISE.sub(" ", job.company or "")
    title = (job.title or "").split("|")[0]
    title = re.sub(r"[\(\[].*?[\)\]]", " ", title)
    title = _TITLE_LOCATION_NOISE.sub(" ", title)
    return f"{_alnum(company)}|{_alnum(title)}"


def source_rank(job: Job) -> int:
    return _SOURCE_RANK.get((job.source or "").lower(), 50)


def dedupe_jobs(jobs: list[Job]) -> list[Job]:
    """Keep one copy per fingerprint, preferring official ATS over scrapers."""
    best: dict[str, Job] = {}
    order: list[str] = []
    for job in jobs:
        fp = job_fingerprint(job)
        prev = best.get(fp)
        if prev is None:
            best[fp] = job
            order.append(fp)
            continue
        if source_rank(job) < source_rank(prev):
            best[fp] = job
    return [best[fp] for fp in order]


def is_data_scientist_title(job: Job, title_family: str | None = None) -> bool:
    """True only for DS-shaped titles (not ML engineer, even if that family matches)."""
    t = (job.title or "").lower()
    if "research" in t:
        return False
    if "data scientist" in t or "decision scientist" in t:
        return True
    if "data science" in t:
        return True
    return False


def is_priority_company(job: Job, companies: list[str]) -> bool:
    name = (job.company or "").lower()
    return any(c.lower() in name for c in companies if c)


def is_priority_ds(job: Job, companies: list[str], title_family: str | None = None) -> bool:
    return is_data_scientist_title(job, title_family) and is_priority_company(job, companies)
