"""Filter, score, dedupe, and email one batch of jobs."""

from __future__ import annotations

from src.dedupe import dedupe_jobs, is_priority_ds, job_fingerprint
from src.emailer import build_digest, dry_run_print, send_digest
from src.filters.company import is_allowed_company, passes_company_filter
from src.filters.freshness import is_fresh_job
from src.filters.location import is_us_job
from src.filters.newgrad import is_new_grad_job
from src.filters.repost import allows_repost
from src.filters.sponsorship import check_sponsorship
from src.filters.title import passes_title_filter
from src.models import Job
from src.scoring.llm import ScoreResult, score_with_llm


def process_batch(
    jobs: list,
    *,
    db,
    profile: dict,
    title_families: dict,
    companies: list[str],
    preferred_locations: list[str],
    interest_keywords: list[str],
    blocked_companies: list[str],
    allowed_companies: list[str],
    require_allowed_company: bool,
    require_us: bool,
    reject_unknown_location: bool,
    require_new_grad: bool,
    strict_new_grad: bool,
    undergrad_only: bool,
    newgrad_require_title_signal: bool,
    threshold: float,
    max_jobs: int,
    max_score: int,
    max_job_age_minutes: float,
    fresh_kwargs: dict,
    emailed_fps: set[str],
    send_priority_now: bool,
    dry_run: bool,
    force_rescore: bool,
    phase: str,
    score_state: dict | None = None,
) -> dict:
    stats = {
        "total": 0,
        "fresh_eligible": 0,
        "already_seen": 0,
        "title_reject": 0,
        "location_reject": 0,
        "company_reject": 0,
        "newgrad_reject": 0,
        "freshness_reject": 0,
        "repost_reject": 0,
        "sponsor_reject": 0,
        "scored": 0,
        "score_capped": 0,
        "emailed": 0,
        "duplicates": 0,
    }
    if not jobs:
        print(f"[{phase}] no jobs")
        return stats

    if require_us:
        before = len(jobs)
        jobs = [
            j
            for j in jobs
            if is_us_job(j, reject_unknown=reject_unknown_location).accept
        ]
        print(f"[{phase}] US location filter: kept {len(jobs)}/{before} jobs")

    before = len(jobs)
    jobs = [
        j
        for j in jobs
        if passes_company_filter(
            j,
            blocked=blocked_companies,
            allowed=allowed_companies,
            require_allowed=require_allowed_company,
        ).accept
    ]
    print(
        f"[{phase}] Company filter: kept {len(jobs)}/{before} jobs "
        f"(known-company={'on' if require_allowed_company else 'off'})"
    )

    reject_reposts = bool(fresh_kwargs.get("reject_reposts", True))
    before = len(jobs)
    not_reposted: list = []
    for j in jobs:
        fp = job_fingerprint(j)
        rp = allows_repost(j, reject_reposts=reject_reposts)
        if rp.accept and reject_reposts and (j.source or "").lower() == "linkedin":
            if db.has_older_fingerprint(fp, j.id, min_age_hours=12.0):
                from src.filters.repost import RepostVerdict

                rp = RepostVerdict(False, "linkedin_clone_repost")
        if rp.accept:
            not_reposted.append(j)
            continue
        stats["repost_reject"] += 1
        db.mark(
            j.id,
            title=j.title,
            company=j.company,
            status="freshness_reject",
            reject_reason=rp.reason,
            fingerprint=fp,
        )
        print(f"  SKIP LinkedIn/ATS repost ({rp.reason}): {j.title} @ {j.company} [{j.source}]")
    jobs = not_reposted
    print(f"[{phase}] Repost filter: kept {len(jobs)}/{before} jobs")

    before = len(jobs)
    titled: list = []
    title_ok_by_id: dict[str, object] = {}
    for j in jobs:
        ok_title, title_verdict = passes_title_filter(j, title_families)
        if ok_title:
            titled.append(j)
            title_ok_by_id[j.id] = title_verdict
    jobs = titled
    print(f"[{phase}] Title filter: kept {len(jobs)}/{before} jobs")

    if require_new_grad:
        before = len(jobs)
        kept = []
        for j in jobs:
            tv = title_ok_by_id.get(j.id)
            title_is_match = bool(tv and getattr(tv, "status", "") == "match")
            title_family = getattr(tv, "family", None) if tv else None
            if is_new_grad_job(
                j,
                strict=strict_new_grad,
                undergrad_only=undergrad_only,
                title_is_match=title_is_match,
                require_title_signal=newgrad_require_title_signal,
                known_company=is_allowed_company(j, allowed_companies, require=True).accept,
                title_family=title_family,
            ).accept:
                kept.append(j)
        jobs = kept
        print(f"[{phase}] Undergrad new-grad filter: kept {len(jobs)}/{before} jobs")

    before = len(jobs)
    jobs = dedupe_jobs(jobs)
    print(f"[{phase}] Cross-source dedupe: {len(jobs)}/{before} unique title+company")

    kept = []
    for j in jobs:
        fp = job_fingerprint(j)
        if fp in emailed_fps or db.was_emailed_fingerprint(fp):
            stats["duplicates"] += 1
            print(
                f"  SKIP duplicate already emailed: {j.title} @ {j.company} [{j.source}]"
            )
            db.mark(
                j.id,
                title=j.title,
                company=j.company,
                status="duplicate",
                emailed=True,
                fingerprint=fp,
            )
            emailed_fps.add(fp)
            continue
        kept.append(j)
    jobs = kept

    def _rank(job) -> tuple:
        tv = title_ok_by_id.get(job.id)
        fam = getattr(tv, "family", None) if tv else None
        pri = is_priority_ds(job, companies, fam)
        ds = fam == "data_scientist" or "data scientist" in (job.title or "").lower()
        return (0 if pri else 1, 0 if ds else 1, job.title.lower())

    jobs.sort(key=_rank)
    eligible_by_id = {j.id: j for j in jobs}

    def _fresh_first_seen(job_id: str) -> str | None:
        status = db.get_status(job_id)
        if status in {
            "title_reject",
            "newgrad_reject",
            "freshness_reject",
            "location_reject",
            "company_reject",
            "sponsor_reject",
            "duplicate",
            None,
        }:
            return None
        return db.first_seen_at(job_id)

    if max_job_age_minutes > 0:
        fresh_count = sum(
            1
            for j in jobs
            if is_fresh_job(
                j,
                first_seen_at=_fresh_first_seen(j.id),
                **fresh_kwargs,
            ).accept
        )
        stats["fresh_eligible"] = fresh_count
        print(
            f"[{phase}] Freshness (≤{max_job_age_minutes:.0f}m): "
            f"{fresh_count}/{len(jobs)} eligible jobs currently fresh"
        )

    stats["total"] = len(jobs)
    digest: list[tuple] = []
    digest_ids: set[str] = set()
    digest_fps: set[str] = set()

    def _mark_emailed(job, score: ScoreResult) -> None:
        fp = job_fingerprint(job)
        emailed_fps.add(fp)
        digest_fps.add(fp)
        db.mark(
            job.id,
            title=job.title,
            company=job.company,
            status="emailed",
            score=score.overall,
            emailed=True,
            fingerprint=fp,
        )

    def _send_now(job, score: ScoreResult, *, label: str) -> None:
        fp = job_fingerprint(job)
        items = [(job, score)]
        if dry_run:
            emailed_fps.add(fp)
            digest_fps.add(fp)
            subject, plain, html_body = build_digest(items)
            dry_run_print(subject, plain, html_body)
            db.mark(
                job.id,
                title=job.title,
                company=job.company,
                status="scored",
                score=score.overall,
                fingerprint=fp,
            )
            return
        subject = send_digest(items)
        print(f"  {label} EMAILED: {subject}")
        _mark_emailed(job, score)
        stats["emailed"] += 1

    def _queue(job, score: ScoreResult, *, skip_freshness: bool = False) -> None:
        fp = job_fingerprint(job)
        if job.id in digest_ids or fp in digest_fps or fp in emailed_fps:
            print(f"  SKIP duplicate queue: {job.title} @ {job.company}")
            return
        rp = allows_repost(job, reject_reposts=reject_reposts)
        if not rp.accept:
            print(f"  SKIP catch-up/queue repost: {job.title} @ {job.company}")
            return
        if len(digest) >= max_jobs:
            return
        if not skip_freshness:
            fresh = is_fresh_job(
                job,
                first_seen_at=_fresh_first_seen(job.id),
                **fresh_kwargs,
            )
            if max_job_age_minutes > 0 and not fresh.accept:
                print(f"  SKIP stale ({fresh.reason}): {job.title} @ {job.company}")
                return
            age = (
                f"{fresh.age_minutes:.0f}m"
                if fresh.age_minutes is not None
                else "?"
            )
        else:
            age = "catchup"
        print(f"  QUEUE {score.overall:.2f} age={age}: {job.title} @ {job.company}")
        digest.append((job, score))
        digest_ids.add(job.id)
        digest_fps.add(fp)

    catchup_by_fp: dict[str, object] = {}
    for row in db.list_unsent_above(threshold):
        fp = job_fingerprint(
            Job(
                id=str(row["job_id"]),
                title=str(row["title"] or ""),
                company=str(row["company"] or ""),
            )
        )
        if fp and fp not in catchup_by_fp:
            catchup_by_fp[fp] = row

    catchup_candidates = 0
    used_catchup_fps: set[str] = set()
    for job in jobs:
        fp = job_fingerprint(job)
        row = catchup_by_fp.get(fp)
        if not row or fp in emailed_fps or fp in used_catchup_fps:
            continue
        if not allows_repost(job, reject_reposts=reject_reposts).accept:
            continue
        used_catchup_fps.add(fp)
        catchup_candidates += 1
        pending = ScoreResult(
            overall=float(row["score"] or 0),
            brief_why=(
                "Previously scored above threshold but not yet emailed; "
                "still listed on the employer board."
            ),
            gaps="Re-check the JD before applying.",
            used_llm=False,
            visa_evidence=[f"Sponsorship field: {job.h1b_sponsored or 'unknown'}"],
        )
        tv = title_ok_by_id.get(job.id)
        fam = getattr(tv, "family", None) if tv else None
        print(
            f"  CATCH-UP {pending.overall:.2f}: {job.title} @ {job.company} [{job.source}]"
        )
        if send_priority_now and is_priority_ds(job, companies, fam):
            _send_now(job, pending, label="PRIORITY DS CATCH-UP")
            continue
        _queue(job, pending, skip_freshness=True)
    print(
        f"[{phase}] Catch-up: {catchup_candidates} still-listed unsent ≥{threshold}; "
        f"queued {len(digest)} so far"
    )

    for job in jobs:
        fp = job_fingerprint(job)
        if fp in emailed_fps:
            stats["already_seen"] += 1
            continue
        status = db.get_status(job.id)
        if not force_rescore and status in {"emailed", "scored", "seen", "duplicate"}:
            stats["already_seen"] += 1
            continue
        if not force_rescore and db.was_emailed(job.id):
            stats["already_seen"] += 1
            continue

        if require_us:
            loc = is_us_job(job, reject_unknown=reject_unknown_location)
            if not loc.accept:
                stats["location_reject"] += 1
                db.mark(
                    job.id,
                    title=job.title,
                    company=job.company,
                    status="location_reject",
                    reject_reason=loc.reason,
                    fingerprint=fp,
                )
                continue

        company_v = passes_company_filter(
            job,
            blocked=blocked_companies,
            allowed=allowed_companies,
            require_allowed=require_allowed_company,
        )
        if not company_v.accept:
            stats["company_reject"] += 1
            db.mark(
                job.id,
                title=job.title,
                company=job.company,
                status="company_reject",
                reject_reason=f"{company_v.reason}:{company_v.matched}",
                fingerprint=fp,
            )
            continue

        ok_title, title_verdict = passes_title_filter(job, title_families)
        if not ok_title:
            stats["title_reject"] += 1
            db.mark(
                job.id,
                title=job.title,
                company=job.company,
                status="title_reject",
                reject_reason=f"{title_verdict.status}:{title_verdict.matched_term}",
                fingerprint=fp,
            )
            continue

        if require_new_grad:
            ng = is_new_grad_job(
                job,
                strict=strict_new_grad,
                undergrad_only=undergrad_only,
                title_is_match=(title_verdict.status == "match"),
                require_title_signal=newgrad_require_title_signal,
                known_company=is_allowed_company(job, allowed_companies, require=True).accept,
                title_family=title_verdict.family,
            )
            if not ng.accept:
                stats["newgrad_reject"] += 1
                db.mark(
                    job.id,
                    title=job.title,
                    company=job.company,
                    status="newgrad_reject",
                    reject_reason=ng.reason,
                    fingerprint=fp,
                )
                continue

        rp = allows_repost(job, reject_reposts=reject_reposts)
        if not rp.accept:
            stats["repost_reject"] += 1
            db.mark(
                job.id,
                title=job.title,
                company=job.company,
                status="freshness_reject",
                reject_reason=rp.reason,
                fingerprint=fp,
            )
            print(f"  REJECT repost: {job.title} @ {job.company} [{job.source}]")
            continue

        if max_job_age_minutes > 0:
            fresh = is_fresh_job(
                job,
                first_seen_at=_fresh_first_seen(job.id),
                **fresh_kwargs,
            )
            if not fresh.accept:
                stats["freshness_reject"] += 1
                db.mark(
                    job.id,
                    title=job.title,
                    company=job.company,
                    status="freshness_reject",
                    reject_reason=fresh.reason,
                    fingerprint=fp,
                )
                continue

        sponsor = check_sponsorship(job)
        if sponsor.reject:
            stats["sponsor_reject"] += 1
            db.mark(
                job.id,
                title=job.title,
                company=job.company,
                status="sponsor_reject",
                reject_reason=sponsor.reason,
                fingerprint=fp,
            )
            print(f"  REJECT sponsor: {job.title} @ {job.company} ({sponsor.reason})")
            continue

        used_scores = score_state["used"] if score_state is not None else stats["scored"]
        is_ds_priority = is_priority_ds(job, companies, title_verdict.family)
        if used_scores >= max_score and not force_rescore and not is_ds_priority:
            stats["score_capped"] += 1
            continue

        score: ScoreResult = score_with_llm(
            job,
            profile=profile,
            title_status=title_verdict.status,
            companies=companies,
            preferred_locations=preferred_locations,
            interest_keywords=interest_keywords,
        )
        stats["scored"] += 1
        if score_state is not None:
            score_state["used"] += 1
        db.mark(
            job.id,
            title=job.title,
            company=job.company,
            status="scored",
            score=score.overall,
            fingerprint=fp,
        )
        print(
            f"  SCORE {score.overall:.2f} ({title_verdict.status}) [{job.source}]: "
            f"{job.title} @ {job.company} [h1b={job.h1b_sponsored}]"
        )

        effective_threshold = threshold if score.used_llm else min(threshold, 0.70)
        if is_ds_priority:
            effective_threshold = min(effective_threshold, 0.55)
        if score.overall < effective_threshold:
            continue

        if send_priority_now and is_ds_priority:
            _send_now(job, score, label="PRIORITY DS")
            continue
        _queue(job, score)

    if digest:
        digest.sort(
            key=lambda pair: (
                0 if is_priority_ds(pair[0], companies) else 1,
                -pair[1].overall,
            )
        )
        digest = digest[:max_jobs]
        if dry_run:
            subject, plain, html_body = build_digest(digest)
            dry_run_print(subject, plain, html_body)
            for job, score in digest:
                db.mark(
                    job.id,
                    title=job.title,
                    company=job.company,
                    status="scored",
                    score=score.overall,
                    fingerprint=job_fingerprint(job),
                )
        else:
            subject = send_digest(digest)
            print(f"  DIGEST EMAILED ({len(digest)} jobs): {subject}")
            for job, score in digest:
                _mark_emailed(job, score)
            stats["emailed"] += len(digest)
    else:
        print(f"[{phase}] No remaining digest jobs to email.")

    print(
        f"[{phase}] Done. total={stats['total']} fresh={stats['fresh_eligible']} "
        f"seen={stats['already_seen']} dups={stats['duplicates']} "
        f"scored={stats['scored']} emailed={stats['emailed']}"
    )
    return stats
