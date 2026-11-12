from __future__ import annotations

import re
from dataclasses import dataclass

from src.models import Job

# Substrings matched case-insensitively against company name.
# Aggregators / AI job platforms that re-post stale listings (not real employers).
DEFAULT_BLOCKED_COMPANIES = [
    "jobright",
    "jobrion",
    "emplo.id",
    "emploid",
    "wellfound",
    "angellist",
    "otta",
    "simplify.jobs",
    "simplify jobs",
    "huntr",
    "lazyapply",
    "fetchjobs",
    "hiredbuddy",
    "hiremap",
    "suprai jobs",
    "supraijobs",
    "jobs ai",
    "jobsai",
    "that startup job",
    "next-gen jobs",
    "jobsinmass",
    "careerscape",
    "careerselite",
    "welcome to the jungle",
    "levels.fyi",
    "arc.dev",
    "braintrust",
    # Staffing / consulting agencies (not direct employers)
    "guidehouse",
    "randstad",
    "adecco",
    "kforce",
    "teksystems",
    "insight global",
    "apex systems",
    "motion recruitment",
    "robert half",
    "cybercoders",
    "aerotek",
    "allegis group",
    "manpower",
    "kelly services",
    "collabera",
    "mindlance",
    "modis",
    "hays",
    "apex group",
    "astrix",
    "tandym group",
    "tandym",
    "procom",
    "motion recruitment",
    "vitamin t",
    "creative circle",
    "aerotek",
    "express employment",
    "staffmark",
    "pridestaff",
    "spherion",
    "appleone",
    "lhh",
    "huxley",
    "michael page",
    "pagegroup",
    "tenth revolution",
    "motion",
    "emonics",
    "matricstek",
    "amoha",
    "rkinfotech",
    "rk infotech",
    "talenthop",
    "talentally",
    "synergisticit",
    "synergistic it",
    "revature",
    "genspark",
    "beaconfire",
    "smoothstack",
    "fdm group",
    "skillstorm",
    "pyramid consulting",
    "compunnel",
    "akraya",
    "judge group",
    "vdart",
    "lanceSoft",
    "lancesoft",
        "artech",
    "kavaliro",
    "disys",
    "dexian",
    "atr international",
]

# Company names that look like staffing / recruiting firms, not employers.
STAFFING_AGENCY_RE = re.compile(
    r"""
    \b(
        guidehouse
        | randstad
        | adecco
        | kforce
        | teksystems
        | insight\s+global
        | apex\s+systems
        | motion\s+recruitment
        | robert\s+half
        | cybercoders
        | aerotek
        | allegis
        | manpower
        | kelly\s+services
        | collabera
        | mindlance
        | modis\b
        | hays\b
        | staffing
        | staff\s+ing
        | recruiting\s+firm
        | recruitment\s+agency
        | talent\s+solutions
        | employment\s+agency
        | job\s+agency
        | placement\s+agency
        | contract\s+staffing
        | workforce\s+solutions
        | personnel\s+services
        | headhunter
        | executive\s+search
    )\b
    """,
    re.IGNORECASE | re.VERBOSE,
)

# JD language typical of third-party recruiters posting on behalf of clients.
THIRD_PARTY_RECRUITER_RE = re.compile(
    r"""
    \b(
        on\s+behalf\s+of\s+(?:our\s+)?client
        | our\s+client\s+is\s+(?:hiring|seeking|looking)
        | hiring\s+for\s+our\s+client
        | contract\s+(?:through|via)\s+(?:our|a)\s+(?:client|agency)
        | third[\s-]party\s+(?:recruiter|agency)
        | staffing\s+(?:firm|agency|partner|company)
        | direct\s+hire\s+for\s+our\s+client
        | placed\s+by\s+(?:a\s+)?staffing
        | through\s+(?:our|a)\s+staffing\s+(?:firm|partner|agency)
    )\b
    """,
    re.IGNORECASE | re.VERBOSE,
)

# Name patterns that scream "job board / marketplace", not an employer.
PLATFORM_NAME_RE = re.compile(
    r"""
    \b(?:ai\s*jobs?|jobs?\s*ai)\b
    | \bjob\s*(?:board|platform|marketplace|aggregator)\b
    | \b(?:job|career)\s*marketplace\b
    | \bfetch\s*jobs\b
    """,
    re.IGNORECASE | re.VERBOSE,
)


@dataclass
class CompanyVerdict:
    accept: bool
    reason: str = "ok"
    matched: str | None = None


def is_blocked_company(
    job: Job,
    blocked: list[str] | None = None,
) -> CompanyVerdict:
    """Reject AI job platforms, staffing agencies, and third-party recruiters."""
    name = (job.company or "").strip()
    if not name:
        return CompanyVerdict(True, "empty_company")

    lower = name.lower()
    terms = [
        t.lower()
        for t in (blocked if blocked is not None else DEFAULT_BLOCKED_COMPANIES)
        if t
    ]
    for term in terms:
        if term and term in lower:
            return CompanyVerdict(False, "blocked_company", term)

    match = PLATFORM_NAME_RE.search(name)
    if match:
        return CompanyVerdict(False, "job_platform_name", match.group(0))

    match = STAFFING_AGENCY_RE.search(name)
    if match:
        return CompanyVerdict(False, "staffing_agency", match.group(0))

    blob = f"{name}\n{job.title}\n{job.qualifications}"
    match = THIRD_PARTY_RECRUITER_RE.search(blob)
    if match:
        return CompanyVerdict(False, "third_party_recruiter", match.group(0))

    return CompanyVerdict(True, "ok")


def is_allowed_company(
    job: Job,
    allowed: list[str] | None = None,
    *,
    require: bool = False,
) -> CompanyVerdict:
    """
    When require=True, only keep well-known / medium-to-large companies
    whose name contains an allowlist substring.
    """
    if not require:
        return CompanyVerdict(True, "allowlist_off")

    name = (job.company or "").strip()
    if not name:
        return CompanyVerdict(False, "unknown_company", None)

    lower = name.lower()
    terms = [t.lower().strip() for t in (allowed or []) if t and str(t).strip()]
    if not terms:
        return CompanyVerdict(True, "empty_allowlist")

    # Longer terms first so "scale ai" beats a hypothetical shorter collision.
    for term in sorted(terms, key=len, reverse=True):
        if term in lower:
            return CompanyVerdict(True, "allowed_company", term)

    return CompanyVerdict(False, "unknown_company", None)


def passes_company_filter(
    job: Job,
    *,
    blocked: list[str] | None = None,
    allowed: list[str] | None = None,
    require_allowed: bool = False,
) -> CompanyVerdict:
    """Block platforms first, then optionally require a known-company allowlist."""
    blocked_v = is_blocked_company(job, blocked)
    if not blocked_v.accept:
        return blocked_v
    return is_allowed_company(job, allowed, require=require_allowed)
