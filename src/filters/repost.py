"""Reject LinkedIn/ATS listings that were bumped, not newly posted."""

from __future__ import annotations

import re
from dataclasses import dataclass

from src.models import Job

# LinkedIn cards say "Reposted 2 days ago". Also catch JD boilerplate.
_REPOST_RE = re.compile(
    r"""
    \b(
        re-?posted
        | this\s+job\s+was\s+re-?posted
        | job\s+re-?posted
        | listing\s+was\s+re-?posted
        | posted\s+again
    )\b
    """,
    re.IGNORECASE | re.VERBOSE,
)


@dataclass
class RepostVerdict:
    accept: bool
    reason: str


def is_reposted_listing(job: Job) -> bool:
    if getattr(job, "is_reposted", False):
        return True
    listing = str((job.raw or {}).get("listing_type") or "").lower()
    if "repost" in listing:
        return True
    blob = f"{job.title}\n{job.qualifications}\n{listing}"
    return bool(_REPOST_RE.search(blob))


def allows_repost(job: Job, *, reject_reposts: bool = True) -> RepostVerdict:
    if not reject_reposts:
        return RepostVerdict(True, "repost_filter_off")
    if is_reposted_listing(job):
        return RepostVerdict(False, "linkedin_repost")
    return RepostVerdict(True, "ok")
