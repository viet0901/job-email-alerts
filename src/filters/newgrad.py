from __future__ import annotations

import re
from dataclasses import dataclass

from src.filters.internship import allows_internship
from src.models import Job

# Strong undergrad / bachelor's new-grad signals (title or description)
_EARLY_RE = re.compile(
    r"""
    \b(
        new\s*grad(?:uate)?s?
        | university\s*grad(?:uate)?s?
        | college\s*grad(?:uate)?s?
        | recent\s*grad(?:uate)?s?
        | undergrad(?:uate)?s?
        | bachelor'?s?
        | b\.?\s*s\.?\b
        | b\.?\s*a\.?\b
        | entry[\s-]*level
        | early[\s-]*career
        | junior
        | jr\.?(?=\s|$)
        | associate
        | university\s+hire
        | campus\s+(?:hire|recruit)
        | graduate\s*(?:program|scheme|role|position|rotational)
        | rotational\s*(?:program|programme|analyst|associate|development)
        | leadership\s*development\s*program
        | 0[\s–\-]+2\s*years?
        | 0[\s–\-]+1\s*years?
        | 1[\s–\-]+2\s*years?
        | less\s+than\s+2\s*years?
        | up\s+to\s+2\s*years?
        | no\s+experience\s+required
        | class\s+of\s+20\d{2}
    )\b
    """,
    re.IGNORECASE | re.VERBOSE,
)

# PhD / postdoc / grad-school research tracks — not undergrad new-grad
_GRAD_SCHOOL_RE = re.compile(
    r"""
    \b(
        ph\.?\s*d\.?
        | phd
        | doctoral
        | doctorate
        | post[\s-]*doc(?:toral)?
        | postdoctoral
        | master'?s(?:\s+or\s+ph\.?\s*d\.?|\s*/\s*ph\.?\s*d\.?)?
        | m\.?\s*s\.?\s*(?:/\s*ph\.?\s*d\.?|\s+or\s+ph\.?\s*d\.?|\s+required|\s+preferred|\s+only|\s+degree|\s+in\s+)
        | m\.?\s*sc\.?
        | mba\s+required
        | advanced\s+degree(?:\s*\(\s*m\.?\s*s\.?|\s+in\s+|\s+required|\s+preferred)
        | graduate\s+degree\s+(?:required|in\s+|or\s+higher)
        | research\s+scientist
        | research\s+engineer
        | ml\s*/\s*research\s+engineer
        | machine\s+learning\s+research\s+engineer
        | research\s+intern\s*\(?\s*phd
        | phd\s+intern
        | phd\s+graduate
        | graduate\s+research
        | applied\s+ai\s+architect
        | ai\s+architect
        | research\s+fellow
    )\b
    """,
    re.IGNORECASE | re.VERBOSE,
)

# Title-level Master's / PhD / Doctoral marker — ALWAYS reject (even if JD mentions BS)
_TITLE_GRAD_ONLY_RE = re.compile(
    r"""
    \b(
        ph\.?\s*d\.?
        | phd
        | doctoral
        | doctorate
        | post[\s-]*doc(?:toral)?
        | master'?s
        | m\.?\s*s\.?\s+(?:grad|university|intern|only|track|program)
        | m\.?\s*sc\.?
        | mba\b
    )\b
    """,
    re.IGNORECASE | re.VERBOSE,
)

# Title-only research track (checked before title_match_allow bypass)
_RESEARCH_TRACK_TITLE_RE = re.compile(
    r"""
    \b(
        research\s+engineer
        | ml\s*/\s*research\s+engineer
        | machine\s+learning\s+research\s+engineer
        | research\s+scientist
        | applied\s+ai\s+architect
        | ai\s+research\s+scientist
        | research\s+fellow
        | doctoral\s+researcher
    )\b
    """,
    re.IGNORECASE | re.VERBOSE,
)

# Explicit "PhD/Master's required/only" style (reject even if bachelor's mentioned elsewhere)
_ADVANCED_DEGREE_ONLY_RE = re.compile(
    r"""
    (
        (?:ph\.?\s*d\.?|phd|doctoral|doctorate|master'?s(?:\s+degree)?|m\.?\s*s\.?\s+degree|m\.?\s*sc\.?|graduate\s+degree|advanced\s+degree)
        \s+(?:is\s+)?(?:required|only|must\s+have|necessary|minimum)
        |
        (?:requires?\s+a\s+|must\s+hold\s+a\s+|must\s+have\s+a\s+|currently\s+pursuing\s+a\s+|in\s+the\s+process\s+of\s+obtaining\s+a\s+)
        (?:ph\.?\s*d\.?|phd|doctoral|doctorate|master'?s(?:\s+degree)?|m\.?\s*s\.?\s+degree|m\.?\s*sc\.?|graduate\s+degree)
        (?!\s*(?:or\s+bachelor|/\s*bachelor|or\s+b\.?\s*[sa]\.?|/\s*b\.?\s*[sa]\.?))
        |
        (?:master'?s|m\.?\s*s\.?|m\.?\s*sc\.?)\s+degree\s+or\s+(?:higher|above|ph\.?\s*d\.?|doctorate|equivalent\s+advanced)
    )
    """,
    re.IGNORECASE | re.VERBOSE,
)

# Senior / mid-career / multi-level titles (II, III, IV, V, 2, 3, 4, 5, L4, L5, VP, etc.)
_SENIOR_TITLE_RE = re.compile(
    r"""
    (
        \b(
            senior
            | sr\.?(?=\s|$)
            | staff
            | principal
            | director
            | manager
            | managing
            | vice\s+president
            | svp
            | evp
            | avp
            | vp
            | head\s+of
            | lead
            | leader
            | fellow
            | distinguished
            | architect
            | founding
        )\b
        |
        # Roman numerals II, III, IV, V or levels 2-9 / L4-L8 on role titles
        \b(?:ii|iii|iv|v|vi)\b
        |
        \b(?:l[4-9]|level\s*[2-9]|lvl\s*[2-9]|grade\s*(?:[6-9]|\d{2}))\b
        |
        \b(?:data\s+scientist|data\s+analyst|machine\s+learning\s+engineer|ml\s+engineer|ai\s+engineer|applied\s+scientist|decision\s+scientist|operations\s+analyst|business\s+analyst|engineer|scientist|analyst)\s+[2-9]\b
    )
    """,
    re.IGNORECASE | re.VERBOSE,
)

# 2+ years required in JD, or qualitative mid/senior experience language
_EXPERIENCED_YEARS_RE = re.compile(
    r"""
    (
        # Range starting at 2+ and ending at 3+: e.g. "2-4 years", "3 to 5 years", "5-9 years"
        \b(?:[2-9]|\d{2})\s*(?:[-–—]|to)\s*(?:[3-9]|\d{2})\+?\s*years?\b
        |
        # 2+ years or 2 or more years (not preceded by "0-" or "1-" or "up to" or "less than")
        (?<!0-)(?<!0–)(?<!0—)(?<!1-)(?<!1–)(?<!1—)(?<!to\s)(?<!than\s)
        \b(?:[2-9]|\d{2})\s*(?:\+|\s+or\s+more)?\s*years?(?:'|\s+of)?\s+
        (?:[a-z/,\-\s]{0,60}?)?
        (?:experience|exp\b|background|work|industry|hands[\s-]*on|role|field|data|analytics|science|engineering|python|sql|machine\s+learning|ml\b|ai\b|modeling|developing|building|managing|leading)
        |
        # "minimum of 2 years", "at least 3 years"
        \b(?:minimum|min\.?|at\s+least)\s+(?:of\s+)?(?:[2-9]|\d{2})\+?\s*years?\b
        |
        # Spelled-out numbers: two / three / four / five+ years of experience
        \b(?:two|three|four|five|six|seven|eight|nine|ten)\s*(?:\+|\s+or\s+more)?\s*years?(?:'|\s+of)?\s+
        (?:[a-z/,\-\s]{0,40}?)?(?:experience|work|background|role|industry)
        |
        # Qualitative mid/senior experience requirements when no number is written
        \b(?:substantial|extensive|significant|proven\s+track\s+record\s+of|several\s+years\s+of|multiple\s+years\s+of|deep\s+hands[\s-]*on)\s+
        (?:[a-z,\-\s]{0,35}?)?(?:experience|background|track\s+record)
        |
        \bthis\s+(?:role|position)\s+is\s+(?:a\s+|an\s+)?(?:director|vice\s+president|vp|senior|lead|staff|principal|mid[\s-]*level|experienced)\b
        |
        \b(?:seeking|looking\s+for)\s+(?:a\s+|an\s+)?(?:mid[\s-]*level|experienced|senior|seasoned|staff|principal)\b
        |
        # High base salary floor ($180k+ / £180k+ / €180k+) is never an undergrad new-grad DA/DS role
        [\$\£\€](?:1[89]\d|[2-9]\d{2}),000
    )
    """,
    re.IGNORECASE | re.VERBOSE,
)

# "1-3 years" is rejected UNLESS the JD also explicitly welcomes recent grads / 0-3 years / internships count
_ONE_TO_THREE_YEARS_RE = re.compile(
    r"\b1\s*(?:[-–—]|to)\s*3\+?\s*years?\b",
    re.IGNORECASE,
)

_ZERO_EXP_WELCOME_RE = re.compile(
    r"""
    \b(
        0[\s–\-]+3\s*years?
        | 0[\s–\-]+2\s*years?
        | 0[\s–\-]+1\s*years?
        | recent\s*grad(?:uate)?s?
        | new\s*grad(?:uate)?s?
        | university\s*grad(?:uate)?s?
        | college\s*grad(?:uate)?s?
        | internships?,?\s+capstones?,?\s+(?:and|or)\s+(?:portfolio\s+)?projects?\s+count
        | no\s+(?:prior\s+)?experience\s+required
    )\b
    """,
    re.IGNORECASE | re.VERBOSE,
)

# Mid-career / customer-facing senior IC titles (rarely undergrad new-grad)
_MID_CAREER_TITLE_RE = re.compile(
    r"""
    \b(
        forward\s+deployed
        | (?<![a-z])fde(?![a-z])
        | solutions\s+architect
        | specialist\s+solutions\s+architect
        | partner\s+solutions\s+architect
        | solutions\s+engineer
        | customer\s+engineer
        | field\s+engineer
        | deployment\s+strategist
        | account\s+executive
        | solutions\s+consultant
        | professional\s+services
    )\b
    """,
    re.IGNORECASE | re.VERBOSE,
)

# Explicit early-career / new-grad signals required in strict mode.
_STRONG_EARLY_OVERRIDE_RE = re.compile(
    r"""
    \b(
        new\s*grad(?:uate)?s?
        | new\s+college\s+grad(?:uate)?s?
        | university\s*grad(?:uate)?s?
        | college\s*grad(?:uate)?s?
        | recent\s*grad(?:uate)?s?
        | entry[\s-]*level
        | early[\s-]*career
        | junior
        | jr\.?(?=\s|$)
        | spring\s*2027
        | spring\s*['']?27
        | campus\s+(?:hire|recruit|program)
        | university\s+hire
        | graduate\s*(?:program|programme|scheme|role|position|rotational|development)
        | rotational\s+(?:program|programme|analyst|associate|development)
        | leadership\s+(?:development\s+)?program
        | technology\s+leadership\s+program
        | class\s+of\s+202[567]
        | 202[67]\s+(?:start|grad|graduate|cohort|program)
        | 0[\s–\-]+3\s*years?
        | 0[\s–\-]+2\s*years?
        | 0[\s–\-]+1\s*years?
        | 1[\s–\-]+2\s*years?
        | less\s+than\s+2\s*years?
        | up\s+to\s+2\s*years?
        | early\s+in\s+their\s+career
        | no\s+experience\s+required
        | no\s+prior\s+experience
    )\b
    """,
    re.IGNORECASE | re.VERBOSE,
)

# Title must look early-career when require_title_signal=True
_TITLE_NEWGRAD_RE = re.compile(
    r"""
    \b(
        new\s*grad(?:uate)?s?
        | new\s+college\s+grad(?:uate)?s?
        | university\s*grad(?:uate)?s?
        | college\s*grad(?:uate)?s?
        | recent\s*grad(?:uate)?s?
        | undergrad(?:uate)?s?
        | entry[\s-]*level
        | early[\s-]*career
        | junior
        | jr\.?(?=\s|$)
        | spring\s*2027
        | spring\s*['']?27
        | campus\s+(?:hire|recruit)
        | university\s+hire
        | graduate\s*(?:program|programme|scheme|role|position|rotational)
        | rotational\s+(?:program|programme|analyst|associate)
        | leadership\s+(?:development\s+)?program
        | bachelor'?s?
        | class\s+of\s+202[567]
        | 202[67]\s+start
        | associate
        | analyst\s+program
    )\b
    """,
    re.IGNORECASE | re.VERBOSE,
)

# Entry-level band in title: "Data Scientist 1", "Analyst I", "Level 1"
# (roman I only — not II/III/IV)
_LEVEL_ONE_TITLE_RE = re.compile(
    r"""
    \b(
        (?:data\s+scientist|data\s+analyst|ai\s+engineer|machine\s+learning\s+engineer|
           ml\s+engineer|business\s+analyst|product\s+analyst|quantitative\s+analyst|analyst|scientist)
        \s*(?:level[\s-]*1|lvl[\s-]*1|1\b|i\b)
    )
    """,
    re.IGNORECASE | re.VERBOSE,
)

_EARLY_OVERRIDE_RE = re.compile(
    r"\b(junior|jr\.?|new\s*grad|entry[\s-]*level|early[\s-]*career|undergrad|university\s+grad|college\s+grad)\b",
    re.IGNORECASE,
)

# Bachelor's explicitly accepted as a degree qualification
_BACHELORS_OK_RE = re.compile(
    r"""
    \b(
        bachelor'?s?(?:\s+degree|\s+or\s+master|\s*/\s*master|\s+in\s+)?
        | b\.?\s*s\.?(?:\s+in\b|\s+or\b|\s*/\s*m\.?\s*s\.?|\s+degree\b)
        | b\.?\s*a\.?(?:\s+in\b|\s+or\b|\s+degree\b)
        | bs\s*/\s*ms\b
        | ba\s*/\s*ms\b
        | bs\s+or\s+ms\b
        | undergraduate\s+degree
        | undergrad
    )\b
    """,
    re.IGNORECASE | re.VERBOSE,
)


@dataclass
class NewGradVerdict:
    accept: bool
    reason: str


def is_new_grad_job(
    job: Job,
    *,
    strict: bool = True,
    undergrad_only: bool = True,
    title_is_match: bool = False,
    require_title_signal: bool = True,
    known_company: bool = False,
    title_family: str | None = None,
) -> NewGradVerdict:
    """
    Strict US undergrad / bachelor's new-grad gate:
      1. Reject internships except Spring 2027.
      2. Reject any senior/mid-level title (Senior, Staff, Principal, VP, Manager,
         II/III/IV/V, Level 2+, L4/L5, 2/3/4/5).
      3. Reject any Master's / PhD / Doctoral in the title (e.g. "Master's University Grad").
      4. Reject any JD that requires 2+ years of experience (or 1-3+ years, or
         qualitative mid/senior experience), even if the title or JD says "New Grad"
         or "Bachelor's".
      5. Reject any JD that requires/prefers Master's or PhD unless Bachelor's (BS/BA)
         is also explicitly accepted.
      6. For bare "Data Scientist" / "Data Analyst" at known companies without an
         explicit new-grad title signal, require non-empty JD text so we can verify
         0-2 years and Bachelor's eligibility.
    """
    title = job.title or ""
    quals = job.qualifications or ""
    blob = f"{title}\n{quals}"

    intern_v = allows_internship(job)
    if not intern_v.accept:
        return NewGradVerdict(False, intern_v.reason)

    early_in_title = bool(_EARLY_RE.search(title))
    level_one_title = bool(_LEVEL_ONE_TITLE_RE.search(title))
    level_one_blob = bool(_LEVEL_ONE_TITLE_RE.search(blob))
    strong_early_title = bool(_STRONG_EARLY_OVERRIDE_RE.search(title)) or level_one_title
    strong_early_blob = bool(_STRONG_EARLY_OVERRIDE_RE.search(blob)) or level_one_blob
    title_newgrad = bool(_TITLE_NEWGRAD_RE.search(title)) or level_one_title
    senior_title = bool(_SENIOR_TITLE_RE.search(title))
    one_to_three_blocked = bool(_ONE_TO_THREE_YEARS_RE.search(blob)) and not bool(
        _ZERO_EXP_WELCOME_RE.search(blob)
    )
    experienced = bool(_EXPERIENCED_YEARS_RE.search(blob)) or one_to_three_blocked
    bachelors_ok = bool(_BACHELORS_OK_RE.search(blob))

    # 1. Hard reject senior / level II+ / manager / VP titles.
    # Note: "Principal Associate" or "Associate Manager" is still mid-level -> reject.
    if senior_title and not _EARLY_OVERRIDE_RE.search(title):
        return NewGradVerdict(False, "senior_title")

    # 2. Hard reject undergrad exclusions (Master's/PhD in title, research tracks, MS/PhD-only JDs)
    if undergrad_only:
        if _TITLE_GRAD_ONLY_RE.search(title):
            return NewGradVerdict(False, "grad_school_title")

        if _RESEARCH_TRACK_TITLE_RE.search(title) and not _EARLY_OVERRIDE_RE.search(title):
            return NewGradVerdict(False, "research_track_title")

        if _MID_CAREER_TITLE_RE.search(title) and not strong_early_title:
            return NewGradVerdict(False, "mid_career_title")

        if _ADVANCED_DEGREE_ONLY_RE.search(blob):
            return NewGradVerdict(False, "advanced_degree_required")

        if _GRAD_SCHOOL_RE.search(blob) and not bachelors_ok:
            return NewGradVerdict(False, "grad_school_track")

    # 3. Hard reject 2+ years of experience — never overridden by "Bachelor's" or "Graduate"
    if experienced:
        return NewGradVerdict(False, "years_experience")

    # 4. Big/known employers: allow bare "Data Scientist" / "Data Analyst" / "AI Engineer"
    # title matches ONLY when we actually have JD text and it has 0 experience & no grad-only restriction.
    da_ds_family = (title_family or "") in {"data_analyst", "data_scientist", "ai_engineer"}
    has_substantive_jd = len(quals.strip()) >= 120
    if (
        known_company
        and title_is_match
        and da_ds_family
        and not senior_title
        and not experienced
        and (strong_early_title or strong_early_blob or (has_substantive_jd and bachelors_ok))
    ):
        return NewGradVerdict(True, "known_company_da_ds")

    # 5. Strict path: require explicit new-grad / junior / entry-level / Level I signal
    if strict:
        if require_title_signal and not title_newgrad:
            if strong_early_blob and title_is_match and has_substantive_jd:
                return NewGradVerdict(True, "early_signal_jd")
            return NewGradVerdict(False, "no_title_newgrad_signal")
        if strong_early_title or title_newgrad:
            return NewGradVerdict(True, "early_signal_title")
        if strong_early_blob:
            return NewGradVerdict(True, "early_signal")
        return NewGradVerdict(False, "no_newgrad_signal")

    if strong_early_title or strong_early_blob or early_in_title:
        return NewGradVerdict(True, "early_signal")
    if title_is_match and not senior_title and has_substantive_jd and bachelors_ok:
        return NewGradVerdict(True, "title_match_allow")
    return NewGradVerdict(False, "no_newgrad_signal")
