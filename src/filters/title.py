from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from src.filters.internship import allows_internship
from src.models import Job


@dataclass
class TitleVerdict:
    status: str  # match | possible | reject | unknown
    family: str | None = None
    matched_term: str | None = None


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text.lower()).strip()


_SENIORITY_RE = re.compile(
    r"\b(senior|sr\.?|staff|principal|director|manager|managing|vice\s+president|svp|evp|avp|vp|head\s+of|lead|leader|fellow|distinguished|architect|founding)\b",
    re.IGNORECASE,
)

# Multi-level indicators (II, III, IV, V, L4, L5, Level 2+, or trailing 2-9)
_HIGHER_LEVEL_TITLE_RE = re.compile(
    r"""
    (
        \b(?:ii|iii|iv|v|vi)\b
        |
        \b(?:l[4-9]|level\s*[2-9]|lvl\s*[2-9]|grade\s*(?:[6-9]|\d{2}))\b
        |
        \b(?:data\s+scientist|data\s+analyst|machine\s+learning\s+engineer|ml\s+engineer|ai\s+engineer|applied\s+scientist|decision\s+scientist|operations\s+analyst|business\s+analyst|engineer|scientist|analyst)\s+[2-9]\b
    )
    """,
    re.IGNORECASE | re.VERBOSE,
)

# Master's / PhD / Doctoral in the title itself — never an undergrad new-grad role
_GRAD_ONLY_TITLE_RE = re.compile(
    r"\b(ph\.?\s*d\.?|phd|doctoral|doctorate|post[\s-]*doc(?:toral)?|master'?s|m\.?\s*sc\.?|mba)\b",
    re.IGNORECASE,
)

# Undergrad pipeline: hard-reject research / PhD-track titles before family matching
_RESEARCH_TRACK_RE = re.compile(
    r"""
    \b(
        research\s+engineer
        | ml\s*/\s*research\s+engineer
        | machine\s+learning\s+research\s+engineer
        | research\s+scientist
        | applied\s+ai\s+architect
        | ai\s+research\s+scientist
        | research\s+fellow
    )\b
    """,
    re.IGNORECASE | re.VERBOSE,
)

_EARLY_TITLE_OVERRIDE_RE = re.compile(
    r"\b(junior|jr\.?|new\s*grad|entry[\s-]*level|intern|undergrad|university\s+grad|college\s+grad)\b",
    re.IGNORECASE,
)

# Non-target business / clinical / HR / sales / GTM roles that happen to contain "Associate", "Graduate", or "Analyst"
_NON_DATA_AI_ROLE_RE = re.compile(
    r"""
    \b(
        patient\s+enrollment
        | customer\s+success
        | account\s+executive
        | account\s+manager
        | sales\s+(?:engineer|operations|representative|associate|analyst)
        | recruiting\s+coordinator
        | talent\s+acquisition
        | human\s+resources
        | legal\s+operations
        | security\s+operations\s+analyst
        | soc\s+analyst
        | cyber\s*security
        | information\s+security
        | attack\s+sensing
        | it\s+support
        | help\s+desk
        | project\s+manager
        | program\s+manager
        | commercial\s+associate
        | real\s+estate
        | facilities
        | payroll
        | accounting
        | audit\s+analyst
        | tax\s+analyst
        | compliance\s+analyst
        | underwriting
        | claims\s+analyst
        | sales\s+finance
        | finance\s+operations\s+analyst
        | revenue\s+operations\s+analyst
    )\b
    """,
    re.IGNORECASE | re.VERBOSE,
)

# Any SWE / SDE-shaped title — always out of scope.
_SWE_RE = re.compile(
    r"""
    \b(
        software(\s+development)?\s+engineer
        | software\s+developer
        | software\s+development
        | software\s+dev\b
        | \bsoftware\b
        | \bswe\b
        | \bsde\b
        | full[\s-]*stack
        | backend(\s+engineer|\s+developer|\s+dev)?
        | front[\s-]*end(\s+engineer|\s+developer|\s+dev)?
        | platform\s+engineer
        | infrastructure\s+engineer
        | reliability\s+engineer
        | devops(\s+engineer)?
        | site\s+reliability
        | \bsre\b
        | mobile\s+engineer
        | ios\s+engineer
        | android\s+engineer
        | web\s+engineer
        | web\s+developer
        | programmer
        | coding\s+engineer
    )\b
    """,
    re.IGNORECASE | re.VERBOSE,
)


def classify_title(job: Job, title_families: dict[str, Any]) -> TitleVerdict:
    title = _normalize(job.title)

    intern_v = allows_internship(job)
    if not intern_v.accept:
        return TitleVerdict(status="reject", family=None, matched_term=intern_v.reason)

    # Master's / PhD / MBA in title is always out for undergrad new-grad
    if _GRAD_ONLY_TITLE_RE.search(title):
        return TitleVerdict(status="reject", family=None, matched_term="grad_degree_title")

    # Any SWE / SDE / generic eng-platform title is out — check first.
    if _SWE_RE.search(title):
        return TitleVerdict(
            status="reject", family=None, matched_term="software_engineering"
        )

    # Non-Data/AI business/ops/security titles
    if _NON_DATA_AI_ROLE_RE.search(title):
        return TitleVerdict(
            status="reject", family=None, matched_term="non_target_role"
        )

    # Research / PhD tracks — not undergrad new-grad targets
    if _RESEARCH_TRACK_RE.search(title) and not _EARLY_TITLE_OVERRIDE_RE.search(title):
        return TitleVerdict(status="reject", family=None, matched_term="research_track")

    # Hard reject mid/senior titles or Level II+ / 2+ for early-career targeting
    if (_SENIORITY_RE.search(title) or _HIGHER_LEVEL_TITLE_RE.search(title)) and not _EARLY_TITLE_OVERRIDE_RE.search(title):
        return TitleVerdict(status="reject", family=None, matched_term="seniority")

    # Reject first across all families
    for family, rules in title_families.items():
        for term in rules.get("reject") or []:
            if _normalize(term) in title:
                return TitleVerdict(status="reject", family=family, matched_term=term)

    best: TitleVerdict | None = None
    for family, rules in title_families.items():
        for term in rules.get("match") or []:
            if _normalize(term) in title:
                return TitleVerdict(status="match", family=family, matched_term=term)
        for term in rules.get("possible") or []:
            if _normalize(term) in title:
                candidate = TitleVerdict(status="possible", family=family, matched_term=term)
                if best is None:
                    best = candidate
    if best:
        return best

    # Soft heuristic for data / AI titles not in lists (must have an analyst/scientist/engineer/developer/quant noun)
    has_role_noun = bool(
        re.search(
            r"\b(analyst|scientist|engineer|developer|quant|quantitative|modeler|specialist|associate)\b",
            title,
        )
    )
    has_domain_noun = (
        "data" in title
        or "analytics" in title
        or "machine learning" in title
        or "decision science" in title
        or "business intelligence" in title
        or "quantitative" in title
        or "rag" in title
        or "llm" in title
        or "genai" in title
        or "generative ai" in title
        or re.search(r"\bml\b", title)
        or re.search(r"\bai\b", title)
    )
    if has_role_noun and has_domain_noun:
        return TitleVerdict(status="possible", family=None, matched_term=None)
    return TitleVerdict(status="unknown", family=None, matched_term=None)


def passes_title_filter(job: Job, title_families: dict[str, Any]) -> tuple[bool, TitleVerdict]:
    verdict = classify_title(job, title_families)
    return verdict.status in {"match", "possible"}, verdict
