"""Reject internships/co-ops except Spring 2027."""

from __future__ import annotations

import re
from dataclasses import dataclass

from src.models import Job

_TITLE_INTERN_RE = re.compile(
    r"\b(intern(?:ship)?|co[\s-]*op(?:\s+program)?|summer\s+analyst|summer\s+associate)\b",
    re.IGNORECASE,
)

# JD-level internship indicators — only when the role ITSELF is an internship
# (not "prior internship experience is a plus")
_JD_INTERN_ROLE_RE = re.compile(
    r"""
    (
        \b(?:this|the|our)\s+(?:is\s+a\s+|full[\s-]*time\s+|part[\s-]*time\s+|summer\s+|fall\s+|winter\s+|spring\s+|\d+[\s-]*week\s+)?
        (?:intern(?:ship)?|co[\s-]*op)\b
        |
        \b(?:summer|fall|winter)\s+202[678]\s+(?:intern(?:ship)?|co[\s-]*op)\b
        |
        \b(?:intern(?:ship)?|co[\s-]*op)\s+(?:position|role|opportunity|program)\s+(?:is\s+|for\s+|designed\s+for\s+|open\s+to\s+)
    )
    """,
    re.IGNORECASE | re.VERBOSE,
)

_SPRING_2027_RE = re.compile(
    r"""
    \b(
        spring\s*['']?27\b
        | spring\s*2027\b
        | spring\s*semester\s*2027\b
        | sp[\s'']?27\b
        | co[\s-]*op\s+spring\s*2027\b
        | internship\s+spring\s*2027\b
        | intern\s+spring\s*2027\b
    )\b
    """,
    re.IGNORECASE | re.VERBOSE,
)


@dataclass
class InternshipVerdict:
    accept: bool
    reason: str


def is_internship_job(job: Job) -> bool:
    if _TITLE_INTERN_RE.search(job.title or ""):
        return True
    return bool(_JD_INTERN_ROLE_RE.search(job.qualifications or ""))


def allows_internship(job: Job) -> InternshipVerdict:
    if not is_internship_job(job):
        return InternshipVerdict(True, "not_internship")
    blob = f"{job.title}\n{job.qualifications}"
    if _SPRING_2027_RE.search(blob):
        return InternshipVerdict(True, "spring_2027_intern")
    return InternshipVerdict(False, "internship_not_spring_2027")
