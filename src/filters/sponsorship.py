from __future__ import annotations

import re
from dataclasses import dataclass

from src.models import Job

# Explicit no-sponsorship / citizenship / security-clearance language.
NO_SPONSOR_PATTERNS = [
    r"will\s+not\s+sponsor",
    r"does\s+not\s+sponsor",
    r"do\s+not\s+sponsor",
    r"won't\s+sponsor",
    r"unable\s+to\s+sponsor",
    r"not\s+able\s+to\s+sponsor",
    r"not\s+offer(?:ing)?\s+(?:visa\s+)?sponsorship",
    r"no\s+visa\s+sponsorship",
    r"no\s+sponsorship(?:\s+available|\s+provided|\s+offered)?",
    r"sponsorship\s+(?:is\s+)?not\s+(?:available|offered|provided)",
    r"sponsorship\s+[^;\n]{0,60}?\bis\s+not\s+(?:available|offered|provided)",
    r"not\s+provid(?:e|ing)\s+(?:visa\s+)?sponsorship",
    r"sponsorship\s+(?:will\s+not|cannot|won't)\s+be\s+(?:provided|available|offered)",
    r"must\s+be\s+authorized\s+to\s+work\s+(?:in\s+the\s+(?:u\.?s\.?|united\s+states)\s+)?without\s+sponsorship",
    r"authorized\s+to\s+work.{0,80}without\s+(?:a\s+requirement\s+for\s+)?(?:work\s+authorization\s+|visa\s+)?sponsorship",
    r"without\s+(?:the\s+need\s+for|requiring|a\s+requirement\s+for)\s+(?:work\s+authorization\s+|visa\s+|employer\s+)?sponsorship",
    r"without\s+(?:visa\s+|work\s+authorization\s+)?sponsorship.{0,50}(?:now|currently).{0,25}(?:and|or).{0,25}(?:in\s+the\s+)?future",
    r"(?:now|currently).{0,25}(?:and|or).{0,25}(?:in\s+the\s+)?future.{0,50}without\s+(?:visa\s+|work\s+authorization\s+)?sponsorship",
    r"requires\s+permanent\s+(?:u\.?\s*s\.?\s+)?work\s+authorization",
    r"immigration\s+sponsorship\s+is\s+not",
    r"u\.?s\.?\s+citizenship\s+(?:is\s+)?required",
    r"must\s+be\s+a\s+u\.?s\.?\s+citizen",
    r"only\s+u\.?s\.?\s+citizens(?:\s+and\s+permanent\s+residents)?\s+(?:will\s+be|are)\s+considered",
    r"(?:active|current|obtain\s+and\s+maintain\s+a?)\s+(?:top\s+secret|ts/sci|secret\s+clearance|public\s+trust|dod\s+clearance)",
    r"\b(?:secret|ts/sci|top\s+secret)\s+security\s+clearance\b",
]

NO_SPONSOR_RE = re.compile("|".join(f"({p})" for p in NO_SPONSOR_PATTERNS), re.IGNORECASE)
# Any posting that says "clearance" or "clearances" is ineligible, including
# "secret clearance", "public trust clearance", and "clearance required".
_CLEARANCE_RE = re.compile(r"\bclearances?\b", re.IGNORECASE)


@dataclass
class SponsorshipVerdict:
    reject: bool
    reason: str | None = None
    evidence: str | None = None


def check_sponsorship(job: Job) -> SponsorshipVerdict:
    blob = job.text_blob
    clearance = _CLEARANCE_RE.search(blob)
    if clearance:
        start = max(0, clearance.start() - 40)
        end = min(len(blob), clearance.end() + 40)
        snippet = " ".join(blob[start:end].split())
        return SponsorshipVerdict(
            reject=True,
            reason="clearance",
            evidence=snippet,
        )

    h1b = (job.h1b_sponsored or "").strip().lower()
    if h1b == "no":
        return SponsorshipVerdict(
            reject=True,
            reason="h1bSponsored=No",
            evidence="Jobright marked h1bSponsored as No",
        )

    match = NO_SPONSOR_RE.search(blob)
    if not match:
        return SponsorshipVerdict(reject=False)

    start = max(0, match.start() - 40)
    end = min(len(blob), match.end() + 40)
    snippet = " ".join(blob[start:end].split())

    return SponsorshipVerdict(
        reject=True,
        reason="no_sponsor_language",
        evidence=snippet,
    )


def is_linkedin_quick_apply(job: Job) -> bool:
    """LinkedIn Easy Apply / Quick Apply. Guest pages mark these as onsite apply links."""
    if (job.source or "").strip().lower() != "linkedin":
        return False
    raw = job.raw or {}
    if raw.get("easy_apply") is True:
        return True
    listing = str(raw.get("listing_type") or "").lower()
    return "easy_apply" in listing or "quick_apply" in listing or "quick apply" in listing
