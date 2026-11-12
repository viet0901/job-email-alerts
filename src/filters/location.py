from __future__ import annotations

import re
from dataclasses import dataclass

from src.models import Job

# Explicit non-US country / region markers (word / phrase level)
_NON_US_PATTERNS = [
    r"\bcanada\b",
    r"\bcanadian\b",
    r"\btoronto\b",
    r"\bvancouver\b",
    r"\bmontreal\b",
    r"\bottawa\b",
    r"\bcalgary\b",
    r"\bmississauga\b",
    r"\bontario\b",
    r"\bbritish columbia\b",
    r"\bquebec\b",
    r"\buk\b",
    r"\bgbr\b",
    r"\bunited kingdom\b",
    r"\bengland\b",
    r"\bscotland\b",
    r"\bwales\b",
    r"\blondon\b",
    r"\bcanary wharf\b",
    r"\bmanchester\b",
    r"\bglasgow\b",
    r"\bedinburgh\b",
    r"\bbirmingham\b",
    r"\bleeds\b",
    r"\bireland\b",
    r"\bdublin\b",
    r"\bgermany\b",
    r"\bberlin\b",
    r"\bmunich\b",
    r"\bfrance\b",
    r"\bparis\b",
    r"\bnetherlands\b",
    r"\bamsterdam\b",
    r"\bindia\b",
    r"\bbangalore\b",
    r"\bbengaluru\b",
    r"\bhyderabad\b",
    r"\bmumbai\b",
    r"\bdelhi\b",
    r"\bpune\b",
    r"\bchennai\b",
    r"\bgurgaon\b",
    r"\bnoida\b",
    r"\bsingapore\b",
    r"\baustralia\b",
    r"\bsydney\b",
    r"\bmelbourne\b",
    r"\bjapan\b",
    r"\btokyo\b",
    r"\bkorea\b",
    r"\bseoul\b",
    r"\bchina\b",
    r"\bshanghai\b",
    r"\bbeijing\b",
    r"\bbrazil\b",
    r"\bsao paulo\b",
    r"\bmexico\b",
    r"\bpoland\b",
    r"\bwarsaw\b",
    r"\bgdynia\b",
    r"\bkrakow\b",
    r"\bkrak[oó]w\b",
    r"\bisrael\b",
    r"\btel aviv\b",
    r"\bhong kong\b",
    r"\bswitzerland\b",
    r"\bzurich\b",
    r"\bgeneva\b",
    r"\bspain\b",
    r"\bmadrid\b",
    r"\bitaly\b",
    r"\bmilan\b",
    r"\bsweden\b",
    r"\bstockholm\b",
    r"\buae\b",
    r"\bdubai\b",
    r"\bphilippines\b",
    r"\bmanila\b",
    r"\bemea\b",
    r"\bapac\b",
    r"\blatam\b",
    r"\beurope\b",
    r"\basia\b",
    r"\bunited states of america\b",  # handled in US list; keep out of non-US
]

# Drop the accidental US-of-America pattern from non-US if I added it — filter below.
_NON_US_PATTERNS = [p for p in _NON_US_PATTERNS if "united states" not in p]

# Positive US signals
_US_PATTERNS = [
    r"\bunited states(?:\s+of\s+america)?\b",
    r"\bu\.?\s*s\.?a\.?\b",
    r"\bu\.?\s*s\.?\b",
    r"\busa\b",
    r"\bremote\b.*\b(us|u\.?s\.?a?|united states)\b",
    r"\b(us|u\.?s\.?a?|united states)\b.*\bremote\b",
    # Common US city / metro hints
    r"\bnew york\b",
    r"\bnyc\b",
    r"\bsan francisco\b",
    r"\bsan jose\b",
    r"\bmountain view\b",
    r"\bsunnyvale\b",
    r"\bpalo alto\b",
    r"\bseattle\b",
    r"\baustin\b",
    r"\bboston\b",
    r"\bchicago\b",
    r"\blos angeles\b",
    r"\bdallas\b",
    r"\bdenver\b",
    r"\batlanta\b",
    r"\bmiami\b",
    r"\bmclean\b",
    r"\breston\b",
    r"\barlington\b",
    r"\bwashington(,?\s*d\.?c\.?)?\b",
    r"\bbay area\b",
    r"\bsilicon valley\b",
    r"\bcalifornia\b",
    r"\btexas\b",
    r"\bwashington\b",
    r"\bmassachusetts\b",
    r"\bvirginia\b",
    r"\bcolorado\b",
    r"\bgeorgia\b",
    r"\bflorida\b",
    r"\bnorth carolina\b",
    r"\bpennsylvania\b",
    r"\billinois\b",
    r"\bnew jersey\b",
    r"\boregon\b",
    r"\barizona\b",
    r"\bcharlotte\b",
    r"\bphiladelphia\b",
    r"\bmalvern\b",
    r"\bdurham\b",
    r"\bwestlake\b",
    r"\bcovington\b",
    r"\bsalt lake\b",
]

# US state abbreviations as standalone tokens (avoid matching CA=Canada context via non-US list first)
_US_STATE_ABBR = (
    r"\b("
    r"AL|AK|AZ|AR|CA|CO|CT|DE|FL|GA|HI|IA|ID|IL|IN|KS|KY|LA|MA|MD|ME|MI|MN|MO|"
    r"MS|MT|NC|ND|NE|NH|NJ|NM|NV|NY|OH|OK|OR|PA|RI|SC|SD|TN|TX|UT|VA|VT|WA|WI|WV|WY|DC"
    r")\b"
)

_NON_US_RE = re.compile("|".join(_NON_US_PATTERNS), re.IGNORECASE)
_US_RE = re.compile("|".join(_US_PATTERNS), re.IGNORECASE)
_STATE_RE = re.compile(_US_STATE_ABBR)
_MULTI_LOC_RE = re.compile(r"^\d+\s+locations?$", re.I)
_EXPLICIT_US_RE = re.compile(
    r"\b(united states(?:\s+of\s+america)?|u\.?s\.?a?\.?|usa)\b",
    re.I,
)


@dataclass
class LocationVerdict:
    accept: bool
    reason: str


def _blob(job: Job) -> str:
    return f"{job.location} {job.work_model}".strip()


def location_text_status(text: str) -> str:
    """Return 'us', 'non_us', 'multi', or 'unknown' for a location string."""
    loc = (text or "").strip()
    if not loc:
        return "unknown"
    if _MULTI_LOC_RE.match(loc):
        return "multi"
    non_us = _NON_US_RE.search(loc)
    us = _US_RE.search(loc) or _STATE_RE.search(loc)
    if non_us and not us:
        return "non_us"
    if non_us and us:
        if _EXPLICIT_US_RE.search(loc):
            return "us"
        return "non_us"
    if us:
        return "us"
    return "unknown"


def is_us_job(job: Job, *, reject_unknown: bool = False) -> LocationVerdict:
    """
    Hard US location gate.

    Accept only with a US city/state/country signal, or Remote without a
    foreign country. Non-US countries always win unless the US is named too.
    """
    loc = _blob(job)
    status = location_text_status(loc)

    if status == "non_us":
        hit = _NON_US_RE.search(loc)
        return LocationVerdict(False, f"non_us:{(hit.group(0) if hit else loc)[:40]}")
    if status == "us":
        return LocationVerdict(True, "us_signal")

    if re.search(r"\b(remote|hybrid|anywhere)\b", loc, re.I):
        return LocationVerdict(True, "remote_allow")

    if not loc or status == "multi":
        if reject_unknown:
            return LocationVerdict(False, "empty_location" if not loc else "multi_unresolved")
        return LocationVerdict(True, "empty_allow")

    if reject_unknown:
        return LocationVerdict(False, "unknown_location")
    return LocationVerdict(True, "unknown_allow")
