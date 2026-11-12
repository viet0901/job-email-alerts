from __future__ import annotations

from src.models import Job
from src.sources.jobspy_boards import fetch_jobspy_jobs


def fetch_linkedin_jobs(
    *,
    search_terms: list[str],
    location: str = "United States",
    results_per_search: int = 25,
    hours_old: int | None = 72,
) -> list[Job]:
    """
    Search LinkedIn via python-jobspy.

    LinkedIn often rate-limits (HTTP 429). Failures for one query are skipped.
    Unofficial scraping — Greenhouse is the reliable path.
    """
    return fetch_jobspy_jobs(
        sites=["linkedin"],
        search_terms=search_terms,
        location=location,
        results_per_search=results_per_search,
        hours_old=hours_old,
        linkedin_fetch_description=True,
        id_prefix="li",
    )
