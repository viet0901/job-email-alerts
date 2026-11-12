from __future__ import annotations

import re

import requests

from src.models import Job

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)

DEFAULT_README_URL = (
    "https://raw.githubusercontent.com/jobright-ai/"
    "2026-Data-Analysis-New-Grad/master/README.md"
)

# Markdown table row: | **[Company](url)** | **[Title](joburl)** | Location | Work Model | Date |
ROW_RE = re.compile(
    r"\|"
    r"\s*\*\*\[(?P<company>[^\]]+)\]\([^)]*\)\*\*\s*\|"
    r"\s*\*\*\[(?P<title>[^\]]+)\]\((?P<url>[^)]+)\)\*\*\s*\|"
    r"\s*(?P<location>[^|]*)\|"
    r"\s*(?P<work_model>[^|]*)\|"
    r"\s*(?P<date>[^|]*)\|",
)

JOB_ID_RE = re.compile(r"/jobs/info/([a-zA-Z0-9]+)")


def fetch_github_jobs(readme_url: str = DEFAULT_README_URL, timeout: int = 30) -> list[Job]:
    resp = requests.get(
        readme_url,
        headers={"User-Agent": USER_AGENT},
        timeout=timeout,
    )
    resp.raise_for_status()
    jobs: list[Job] = []
    seen: set[str] = set()
    for match in ROW_RE.finditer(resp.text):
        url = match.group("url").strip()
        id_match = JOB_ID_RE.search(url)
        job_id = id_match.group(1) if id_match else url
        if job_id in seen:
            continue
        seen.add(job_id)
        jobs.append(
            Job(
                id=job_id,
                title=match.group("title").strip(),
                company=match.group("company").strip(),
                location=match.group("location").strip(),
                work_model=match.group("work_model").strip(),
                apply_url=url.split("?")[0],
                qualifications="",
                h1b_sponsored=None,
                category="data_analysis",
                source="github_fallback",
            )
        )
    return jobs
