from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from typing import Any

from src.models import Job

DEFAULT_RESUME_PATH = "/Users/minhvietnguyen/Documents/New Grad 26/Data Science (ML)/VietN_Resume.pdf"


@dataclass
class ScoreResult:
    role_family: str = "unknown"
    seniority: str = "unknown"
    title_match: float = 0.0
    resume_fit: float = 0.0
    experience_fit: float = 0.0
    opt_fit: float = 0.5
    sponsorship_fit: float = 0.5
    freshness: float = 0.7
    location_fit: float = 0.5
    company_priority: float = 0.0
    visa_evidence: list[str] = field(default_factory=list)
    brief_why: str = ""
    gaps: str = ""
    matched_keywords: list[str] = field(default_factory=list)
    missing_keywords: list[str] = field(default_factory=list)
    tailored_bullets: list[str] = field(default_factory=list)
    overall: float = 0.0
    used_llm: bool = False
    raw: dict[str, Any] = field(default_factory=dict)


WEIGHTS = {
    "resume_fit": 0.30,
    "title_match": 0.20,
    "experience_fit": 0.15,
    "opt_visa": 0.15,
    "freshness": 0.10,
    "company_priority": 0.05,
    "location_fit": 0.05,
}

# Canonical ATS keywords scanned across JDs:
# (display_label, regex_pattern, is_on_VietN_Resume_pdf)
_ATS_KEYWORD_CATALOG: list[tuple[str, str, bool]] = [
    ("Python", r"\bpython\b", True),
    ("SQL", r"\bsql\b", True),
    ("R (caret, dplyr, ggplot2)", r"\br\b(?:\s+programming|\s*,\s*python|\s+or\s+python|\s+and\s+python)", True),
    ("pandas", r"\bpandas\b", True),
    ("scikit-learn", r"\bscikit[\s-]*learn\b|\bsklearn\b", True),
    ("PySpark / Spark", r"\b(?:py)?spark\b", True),
    ("PyTorch", r"\bpytorch\b", True),
    ("TensorFlow", r"\btensorflow\b", True),
    ("Snowflake", r"\bsnowflake\b", True),
    ("Tableau", r"\btableau\b", True),
    ("Excel", r"\bexcel\b", True),
    ("DuckDB", r"\bduckdb\b", True),
    ("MySQL / Relational DB", r"\bmysql\b|\brelational\s+database\b", True),
    ("Streamlit", r"\bstreamlit\b", True),
    ("Docker", r"\bdocker\b", True),
    ("Git / GitHub", r"\bgit\b|\bgithub\b", True),
    ("Jira", r"\bjira\b", True),
    ("Azure", r"\bazure\b", True),
    ("ChromaDB / Vector DB", r"\bchromadb\b|\bembeddings?\b|\bvector\s+(?:database|db|store|search)\b", True),
    ("LLMs / GenAI", r"\bllms?\b|\blarge\s+language\s+models?\b|\bgenerative\s+ai\b|\bgenai\b|\bclaude\b|\bopenai\b", True),
    ("RAG / Knowledge Retrieval", r"\brag\b|\bretrieval[\s-]*augmented\b|\bknowledge\s+base\b", True),
    ("Random Forest / XGBoost", r"\brandom\s+forest\b|\bxgboost\b|\blightgbm\b|\bgradient\s+boost(?:ing|ed)\b", True),
    ("Regression / Classification", r"\bregression\b|\bclassification\b|\blogistic\s+regression\b", True),
    ("Deep Learning / CNN", r"\bdeep\s+learning\b|\bneural\s+networks?\b|\bcnn\b|\btransformers?\b", True),
    ("NLP", r"\bnlp\b|\bnatural\s+language\s+processing\b", True),
    ("Computer Vision", r"\bcomputer\s+vision\b|\bimage\s+classification\b", True),
    ("Time Series / Forecasting (SARIMA)", r"\btime[\s-]*series\b|\bforecasting\b|\bsarima\b|\barima\b", True),
    ("Monte Carlo Simulation", r"\bmonte\s+carlo\b|\bsimulation\b", True),
    ("Bayesian Inference", r"\bbayesian\b", True),
    ("Hypothesis Testing", r"\bhypothesis\s+testing\b|\bstatistical\s+modeling\b", True),
    ("A/B Testing", r"\ba/b\s+test(?:ing|s)?\b|\bexperimentation\b", True),
    ("SHAP / Explainable AI", r"\bshap\b|\binterpretability\b|\bexplainab(?:le|ility)\b|\bgrad[\s-]*cam\b", True),
    ("Clustering / Segmentation (K-means, RFM)", r"\bk[\s-]*means\b|\bclustering\b|\bsegmentation\b|\brfm\b|\bsurvival\s+analysis\b", True),
    ("Financial / Credit Risk Analytics", r"\bcredit\s+risk\b|\bloan\b|\bfinancial\s+statements?\b|\bbanking\b|\bdscr\b", True),
    # Keywords NOT currently listed on VietN_Resume.pdf (flagged as missing when JD requests them)
    ("Power BI", r"\bpower\s*bi\b", False),
    ("Looker", r"\blooker\b", False),
    ("Causal Inference", r"\bcausal\s+inference\b|\bdifference[\s-]*in[\s-]*differences\b|\bsynthetic\s+control\b", False),
    ("LangChain / LangGraph / LlamaIndex", r"\blangchain\b|\blanggraph\b|\bllamaindex\b", False),
    ("Fine-Tuning / RLHF / LoRA", r"\bfine[\s-]*tun(?:ing|e)\b|\brlhf\b|\blo-?ra\b|\bdpo\b", False),
    ("dbt", r"\bdbt\b", False),
    ("Airflow", r"\bairflow\b", False),
    ("Databricks", r"\bdatabricks\b", False),
    ("BigQuery", r"\bbigquery\b", False),
    ("Redshift", r"\bredshift\b", False),
    ("AWS (SageMaker / Bedrock / S3)", r"\baws\b|\bsagemaker\b|\bbedrock\b", False),
    ("GCP / Vertex AI", r"\bgcp\b|\bgoogle\s+cloud\b|\bvertex\s+ai\b", False),
    ("Kubernetes", r"\bkubernetes\b|\bk8s\b", False),
    ("FastAPI / REST Microservices", r"\bfastapi\b|\bflask\b|\bmicroservices?\b", False),
    ("CI/CD Pipelines", r"\bci/cd\b|\bmlops\b", False),
]


def _clamp(x: float) -> float:
    return max(0.0, min(1.0, float(x)))


def _weighted_overall(parts: dict[str, float]) -> float:
    opt_visa = (parts["opt_fit"] + parts["sponsorship_fit"]) / 2.0
    total = (
        WEIGHTS["resume_fit"] * parts["resume_fit"]
        + WEIGHTS["title_match"] * parts["title_match"]
        + WEIGHTS["experience_fit"] * parts["experience_fit"]
        + WEIGHTS["opt_visa"] * opt_visa
        + WEIGHTS["freshness"] * parts["freshness"]
        + WEIGHTS["company_priority"] * parts["company_priority"]
        + WEIGHTS["location_fit"] * parts["location_fit"]
    )
    return _clamp(total)


def extract_ats_keywords(job: Job) -> tuple[list[str], list[str]]:
    """Scan JD text against VietN_Resume.pdf skills -> (matched_on_resume, missing_from_resume)."""
    blob = f"{job.title}\n{job.qualifications}".lower()
    matched: list[str] = []
    missing: list[str] = []
    for label, pattern, in_profile in _ATS_KEYWORD_CATALOG:
        if re.search(pattern, blob, re.I):
            if in_profile:
                matched.append(label)
            else:
                missing.append(label)
    return matched[:8], missing[:8]


def build_fallback_bullets(
    job: Job,
    *,
    matched_keywords: list[str],
    missing_keywords: list[str],
) -> list[str]:
    """Adapt actual bullets from VietN_Resume.pdf to mirror the target job's keywords."""
    extra = f" ({', '.join(missing_keywords[:2])})" if missing_keywords else ""
    return [
        f"[Park National Bank] Developed a Random Forest & XGBoost classifier in Python (scikit-learn, pandas){extra} on 100,000+ commercial deals to automate credit review, achieving 90% test accuracy and supporting $12M+ in monthly approvals.",
        f"[Park National Bank] Analyzed 500,000+ customer records using Snowflake SQL and Tableau to surface account trends, build AI-assisted product recommendations, and deliver executive KPI dashboards.",
        f"[VIUM Capital / Red Frame Lab] Built production LLM & RAG extraction pipelines with Claude, OpenAI o3, Azure VM, and ChromaDB across 200+ financial statements and 12+ TPA report formats, achieving 95% validation accuracy and cutting manual review time by 90–98%.",
    ]


def ensure_ats_guidance(job: Job, score: ScoreResult) -> ScoreResult:
    """Populate matched_keywords, missing_keywords, and tailored_bullets against VietN_Resume.pdf."""
    det_matched, det_missing = extract_ats_keywords(job)

    seen_m: set[str] = set()
    merged_matched: list[str] = []
    for kw in list(score.matched_keywords or []) + det_matched:
        k = str(kw).strip()
        if k and k.lower() not in seen_m:
            seen_m.add(k.lower())
            merged_matched.append(k)
    score.matched_keywords = merged_matched[:8]

    seen_gap: set[str] = set(seen_m)
    merged_missing: list[str] = []
    for kw in list(score.missing_keywords or []) + det_missing:
        k = str(kw).strip()
        if k and k.lower() not in seen_gap:
            seen_gap.add(k.lower())
            merged_missing.append(k)
    score.missing_keywords = merged_missing[:8]

    if not score.tailored_bullets:
        score.tailored_bullets = build_fallback_bullets(
            job,
            matched_keywords=score.matched_keywords,
            missing_keywords=score.missing_keywords,
        )
    return score


def company_priority_score(job: Job, companies: list[str]) -> float:
    name = (job.company or "").lower()
    for c in companies:
        if c.lower() in name:
            return 1.0
    return 0.0


def apply_ds_priority_boost(job: Job, overall: float, companies: list[str]) -> float:
    """Bump Data Scientist roles at target big companies so they clear email threshold ASAP."""
    from src.dedupe import is_data_scientist_title, is_priority_company

    if not is_data_scientist_title(job):
        return overall
    if not is_priority_company(job, companies):
        return overall
    return _clamp(overall + 0.08)


def location_fit_score(job: Job, preferred: list[str]) -> float:
    if not preferred:
        return 0.5
    blob = f"{job.location} {job.work_model}".lower()
    for loc in preferred:
        if loc.lower() in blob:
            return 1.0
    return 0.3


def interest_keyword_boost(job: Job, keywords: list[str]) -> float:
    """Return 0–0.25 boost when JD mentions preferred AI/DS tech."""
    if not keywords:
        return 0.0
    blob = job.text_blob.lower()
    hits = sum(1 for kw in keywords if kw.lower() in blob)
    if hits == 0:
        return 0.0
    return _clamp(0.08 * hits)


def heuristic_score(
    job: Job,
    *,
    title_status: str,
    companies: list[str],
    preferred_locations: list[str],
    interest_keywords: list[str] | None = None,
) -> ScoreResult:
    title_map = {"match": 0.9, "possible": 0.65, "unknown": 0.4, "reject": 0.1}
    title_match = title_map.get(title_status, 0.4)

    det_matched, _ = extract_ats_keywords(job)
    skills_hit = len(det_matched)
    blob = job.text_blob.lower()
    resume_fit = _clamp(0.45 + 0.08 * skills_hit + interest_keyword_boost(job, interest_keywords or []))

    experience_fit = 0.75
    if re.search(
        r"\b("
        r"0[\s–-]*2|1[\s–-]*2|1\+?\s*years?"
        r"|new\s*grad|entry[\s-]*level|junior"
        r"|at\s+least\s+1\s+year"
        r")\b",
        blob,
        re.I,
    ):
        experience_fit = 0.9
    if re.search(r"\b(5\+?\s*years|7\+?\s*years|10\+?\s*years|senior)\b", blob, re.I):
        experience_fit = 0.25

    h1b = (job.h1b_sponsored or "").lower()
    if h1b == "yes":
        sponsorship_fit, opt_fit = 0.95, 0.85
        evidence = ["Jobright marked h1bSponsored as Yes"]
    elif h1b == "not sure":
        sponsorship_fit, opt_fit = 0.55, 0.6
        evidence = ["Jobright marked h1bSponsored as Not Sure"]
    else:
        sponsorship_fit, opt_fit = 0.5, 0.55
        evidence = ["No clear sponsorship signal in listing metadata"]

    parts = {
        "resume_fit": resume_fit,
        "title_match": title_match,
        "experience_fit": experience_fit,
        "opt_fit": opt_fit,
        "sponsorship_fit": sponsorship_fit,
        "freshness": 0.85,
        "company_priority": company_priority_score(job, companies),
        "location_fit": location_fit_score(job, preferred_locations),
    }
    overall = _weighted_overall(parts)
    overall = apply_ds_priority_boost(job, overall, companies)
    res = ScoreResult(
        role_family="data_related",
        seniority="entry_level",
        title_match=title_match,
        resume_fit=resume_fit,
        experience_fit=experience_fit,
        opt_fit=opt_fit,
        sponsorship_fit=sponsorship_fit,
        freshness=parts["freshness"],
        location_fit=parts["location_fit"],
        company_priority=parts["company_priority"],
        visa_evidence=evidence,
        brief_why=(
            f"Matched against your default resume (VietN_Resume.pdf) with {skills_hit} overlapping technical skills. "
            f"Sponsorship signal: {job.h1b_sponsored or 'unknown'}."
        ),
        gaps="LLM unavailable — see ATS keyword checklist below to tailor VietN_Resume.pdf.",
        overall=overall,
        used_llm=False,
    )
    return ensure_ats_guidance(job, res)


def _extract_json(text: str) -> dict[str, Any]:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if not match:
            raise
        return json.loads(match.group(0))


def _build_prompt(job: Job, profile: dict[str, Any], title_status: str) -> str:
    return f"""You score how well a job fits Viet Nguyen's default resume ({DEFAULT_RESUME_PATH}) AND generate an ATS tailoring pack by adapting his ACTUAL resume bullets to this job description.
Use ONLY evidence from the job text and the candidate's real resume in the profile below. Do NOT invent sponsorship policy from company reputation.

This candidate is an UNDERGRADUATE new graduate (B.S. in Data Analytics & Mathematics at Denison University, GPA 3.78, graduating Dec 2026) with 4 internships (VIUM Capital AI Engineer Intern, Park National Bank Data Science Intern, Benefactor Group Data Science Intern, Legacy Agencies Data Science Intern).
- Boost experience_fit for bachelor's new-grad / campus / entry-level / junior / 0-2 year roles
- Heavily penalize experience_fit for PhD-required, postdoc, doctoral, Master's-only, or 2+ years required roles

For the ATS Tailoring fields (based strictly on VietN_Resume.pdf):
1. "matched_keywords": Up to 6 exact technical skills/tools/methods in the JD that ARE ALREADY on VietN_Resume.pdf.
2. "missing_keywords": Up to 6 exact ATS keywords, tools, cloud platforms, or domain terms in the JD that are NOT on VietN_Resume.pdf and should be added/mirrored before applying.
3. "tailored_bullets": Pick the 3 most relevant bullets from Viet's ACTUAL experience/projects (VIUM Capital, Park National Bank, Benefactor Group, Legacy Agencies, CNN Study, GiveSmart, or Red Frame Lab AI Pipeline) and lightly rewrite them so they naturally incorporate this job's exact JD keywords while preserving Viet's real metrics (e.g., 200+ financial statements / 98% time reduction; 100,000+ commercial deals / 90% accuracy / $12M+ monthly approvals; 500,000+ customer records in Snowflake SQL & Tableau; OpenAI o3 + ChromaDB / 95% accuracy). Prefix each bullet with the section name in brackets, e.g. "[Park National Bank] ..." or "[VIUM Capital] ...".

Return ONLY valid JSON with this schema:
{{
  "role_family": "data_analyst|data_scientist|ai_engineer|other",
  "seniority": "entry_level|mid|senior|unknown",
  "title_match": 0.0-1.0,
  "resume_fit": 0.0-1.0,
  "experience_fit": 0.0-1.0,
  "opt_fit": 0.0-1.0,
  "sponsorship_fit": 0.0-1.0,
  "visa_evidence": ["short quotes from the job text only, or note if none"],
  "brief_why": "2-3 sentences referencing specific internships/projects on VietN_Resume.pdf",
  "gaps": "one short gap vs VietN_Resume.pdf if any",
  "matched_keywords": ["exact JD keyword already on VietN_Resume.pdf"],
  "missing_keywords": ["exact JD keyword missing from VietN_Resume.pdf"],
  "tailored_bullets": [
    "[Experience/Project Name] Rewritten bullet 1 using Viet's real metrics + exact JD keywords",
    "[Experience/Project Name] Rewritten bullet 2 using Viet's real metrics + exact JD keywords",
    "[Experience/Project Name] Rewritten bullet 3 using Viet's real metrics + exact JD keywords"
  ]
}}

Candidate default resume (VietN_Resume.pdf):
{json.dumps(profile, indent=2)}

Title prefilter status: {title_status}
Jobright h1bSponsored field: {job.h1b_sponsored}

JOB:
Title: {job.title}
Company: {job.company}
Location: {job.location}
Work model: {job.work_model}
Salary: {job.salary}
Qualifications:
{job.qualifications}
"""


def _as_str_list(val: Any, limit: int = 8) -> list[str]:
    if not val:
        return []
    if isinstance(val, str):
        return [val.strip()] if val.strip() else []
    if isinstance(val, list):
        return [str(x).strip() for x in val if str(x).strip()][:limit]
    return []


def score_with_llm(
    job: Job,
    *,
    profile: dict[str, Any],
    title_status: str,
    companies: list[str],
    preferred_locations: list[str],
    interest_keywords: list[str] | None = None,
    provider: str | None = None,
) -> ScoreResult:
    provider = (provider or os.getenv("LLM_PROVIDER", "gemini")).lower().strip()
    groq_key = os.getenv("GROQ_API_KEY", "").strip()
    gemini_key = os.getenv("GEMINI_API_KEY", "").strip()
    keywords = interest_keywords or []

    def _fallback() -> ScoreResult:
        return heuristic_score(
            job,
            title_status=title_status,
            companies=companies,
            preferred_locations=preferred_locations,
            interest_keywords=keywords,
        )

    if provider == "groq" and not groq_key:
        if gemini_key:
            provider = "gemini"
        else:
            return _fallback()
    if provider == "gemini" and not gemini_key:
        if groq_key:
            provider = "groq"
        else:
            return _fallback()
    if provider not in {"groq", "gemini"}:
        return _fallback()

    prompt = _build_prompt(job, profile, title_status)
    raw_text = ""
    if provider == "gemini":
        try:
            raw_text = _call_gemini(prompt, gemini_key)
        except Exception as exc:  # noqa: BLE001 — rate limits / 503 blips
            if groq_key:
                try:
                    raw_text = _call_groq(prompt, groq_key)
                except Exception as groq_exc:  # noqa: BLE001
                    print(f"  LLM fallback (gemini->{groq_exc}): {exc}")
                    return _fallback()
            else:
                print(f"  LLM fallback (gemini): {exc}")
                return _fallback()
    else:
        try:
            raw_text = _call_groq(prompt, groq_key)
        except Exception as exc:  # noqa: BLE001
            if gemini_key:
                try:
                    raw_text = _call_gemini(prompt, gemini_key)
                except Exception as gem_exc:  # noqa: BLE001
                    print(f"  LLM fallback (groq->{gem_exc}): {exc}")
                    return _fallback()
            else:
                print(f"  LLM fallback (groq): {exc}")
                return _fallback()

    data = _extract_json(raw_text)
    resume_fit = _clamp(data.get("resume_fit", 0.5) + interest_keyword_boost(job, keywords))
    parts = {
        "resume_fit": resume_fit,
        "title_match": _clamp(data.get("title_match", 0.5)),
        "experience_fit": _clamp(data.get("experience_fit", 0.5)),
        "opt_fit": _clamp(data.get("opt_fit", 0.5)),
        "sponsorship_fit": _clamp(data.get("sponsorship_fit", 0.5)),
        "freshness": 0.85,
        "company_priority": company_priority_score(job, companies),
        "location_fit": location_fit_score(job, preferred_locations),
    }
    h1b = (job.h1b_sponsored or "").lower()
    if h1b == "yes":
        parts["sponsorship_fit"] = max(parts["sponsorship_fit"], 0.85)
    elif h1b == "not sure":
        parts["sponsorship_fit"] = min(max(parts["sponsorship_fit"], 0.4), 0.7)

    evidence = _as_str_list(data.get("visa_evidence"), limit=6)

    res = ScoreResult(
        role_family=str(data.get("role_family") or "unknown"),
        seniority=str(data.get("seniority") or "unknown"),
        title_match=parts["title_match"],
        resume_fit=parts["resume_fit"],
        experience_fit=parts["experience_fit"],
        opt_fit=parts["opt_fit"],
        sponsorship_fit=parts["sponsorship_fit"],
        freshness=parts["freshness"],
        location_fit=parts["location_fit"],
        company_priority=parts["company_priority"],
        visa_evidence=evidence,
        brief_why=str(data.get("brief_why") or ""),
        gaps=str(data.get("gaps") or ""),
        matched_keywords=_as_str_list(data.get("matched_keywords"), limit=8),
        missing_keywords=_as_str_list(data.get("missing_keywords"), limit=8),
        tailored_bullets=_as_str_list(data.get("tailored_bullets"), limit=4),
        overall=(
            0.20
            if str(data.get("seniority") or "").lower().strip() in {"mid", "senior", "lead", "staff", "principal", "director"}
            or parts["experience_fit"] < 0.35
            or parts["sponsorship_fit"] < 0.25
            or parts["opt_fit"] < 0.25
            else apply_ds_priority_boost(job, _weighted_overall(parts), companies)
        ),
        used_llm=True,
        raw=data,
    )
    return ensure_ats_guidance(job, res)


def _call_groq(prompt: str, api_key: str) -> str:
    from groq import Groq

    client = Groq(api_key=api_key)
    primary = os.getenv("GROQ_MODEL", "openai/gpt-oss-120b").strip()
    candidates = list(dict.fromkeys([primary, "openai/gpt-oss-120b", "qwen/qwen3.8-27b"]))
    last_exc: Exception | None = None
    for model in candidates:
        if not model:
            continue
        try:
            completion = client.chat.completions.create(
                model=model,
                messages=[
                    {
                        "role": "system",
                        "content": "You are a careful job-fit scorer and ATS resume coach. Reply with JSON only.",
                    },
                    {"role": "user", "content": prompt},
                ],
                temperature=0.2,
                response_format={"type": "json_object"},
            )
            return completion.choices[0].message.content or "{}"
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
            continue
    if last_exc:
        raise last_exc
    return "{}"


def _call_gemini(prompt: str, api_key: str) -> str:
    from google import genai

    client = genai.Client(api_key=api_key)
    primary = os.getenv("GEMINI_MODEL", "gemini-3.6-flash").strip()
    candidates = list(
        dict.fromkeys([primary, "gemini-3.6-flash", "gemini-3.5-flash-lite"])
    )
    last_exc: Exception | None = None
    for model_name in candidates:
        if not model_name:
            continue
        try:
            result = client.models.generate_content(
                model=model_name,
                contents=(
                    "You are a careful job-fit scorer and ATS resume coach. Reply with JSON only.\n\n"
                    + prompt
                ),
                config={
                    "response_mime_type": "application/json",
                    "temperature": 0.2,
                    "automatic_function_calling": {"disable": True},
                },
            )
            return result.text or "{}"
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
            continue
    if last_exc:
        raise last_exc
    return "{}"
