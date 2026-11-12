from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path


class JobDB:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.path)
        self._conn.row_factory = sqlite3.Row
        self._init_schema()

    def _init_schema(self) -> None:
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS seen_jobs (
                job_id TEXT PRIMARY KEY,
                title TEXT,
                company TEXT,
                first_seen_at TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'seen',
                score REAL,
                emailed_at TEXT,
                reject_reason TEXT,
                fingerprint TEXT
            )
            """
        )
        cols = {
            row["name"]
            for row in self._conn.execute("PRAGMA table_info(seen_jobs)").fetchall()
        }
        if "fingerprint" not in cols:
            self._conn.execute("ALTER TABLE seen_jobs ADD COLUMN fingerprint TEXT")
        self._conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_seen_fingerprint ON seen_jobs(fingerprint)"
        )
        self._conn.commit()

    def is_seen(self, job_id: str) -> bool:
        row = self._conn.execute(
            "SELECT 1 FROM seen_jobs WHERE job_id = ?", (job_id,)
        ).fetchone()
        return row is not None

    def mark(
        self,
        job_id: str,
        *,
        title: str = "",
        company: str = "",
        status: str = "seen",
        score: float | None = None,
        reject_reason: str | None = None,
        emailed: bool = False,
        fingerprint: str | None = None,
    ) -> None:
        now = datetime.now(timezone.utc).isoformat()
        existing = self._conn.execute(
            "SELECT first_seen_at FROM seen_jobs WHERE job_id = ?", (job_id,)
        ).fetchone()
        first_seen = existing["first_seen_at"] if existing else now
        emailed_at = now if emailed else None
        if not fingerprint and title and company:
            from src.dedupe import job_fingerprint
            from src.models import Job

            fingerprint = job_fingerprint(Job(id=job_id, title=title, company=company))
        self._conn.execute(
            """
            INSERT INTO seen_jobs (
                job_id, title, company, first_seen_at, status, score,
                emailed_at, reject_reason, fingerprint
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(job_id) DO UPDATE SET
                title = excluded.title,
                company = excluded.company,
                status = excluded.status,
                score = COALESCE(excluded.score, seen_jobs.score),
                emailed_at = COALESCE(excluded.emailed_at, seen_jobs.emailed_at),
                reject_reason = COALESCE(excluded.reject_reason, seen_jobs.reject_reason),
                fingerprint = COALESCE(excluded.fingerprint, seen_jobs.fingerprint)
            """,
            (
                job_id,
                title,
                company,
                first_seen,
                status,
                score,
                emailed_at,
                reject_reason,
                fingerprint,
            ),
        )
        self._conn.commit()

    def first_seen_at(self, job_id: str) -> str | None:
        row = self._conn.execute(
            "SELECT first_seen_at FROM seen_jobs WHERE job_id = ?", (job_id,)
        ).fetchone()
        return row["first_seen_at"] if row else None

    def list_unsent_above(self, threshold: float) -> list[sqlite3.Row]:
        """Jobs scored at/above threshold that were never emailed (e.g. run crashed)."""
        return list(
            self._conn.execute(
                """
                SELECT job_id, title, company, score
                FROM seen_jobs
                WHERE score IS NOT NULL
                  AND score >= ?
                  AND emailed_at IS NULL
                  AND status IN ('scored', 'seen')
                ORDER BY score DESC
                """,
                (threshold,),
            ).fetchall()
        )

    def get_status(self, job_id: str) -> str | None:
        row = self._conn.execute(
            "SELECT status FROM seen_jobs WHERE job_id = ?", (job_id,)
        ).fetchone()
        return row["status"] if row else None

    def was_emailed(self, job_id: str) -> bool:
        row = self._conn.execute(
            "SELECT emailed_at FROM seen_jobs WHERE job_id = ?", (job_id,)
        ).fetchone()
        return bool(row and row["emailed_at"])

    def was_emailed_fingerprint(self, fingerprint: str) -> bool:
        if not fingerprint:
            return False
        row = self._conn.execute(
            """
            SELECT 1 FROM seen_jobs
            WHERE fingerprint = ? AND emailed_at IS NOT NULL
            LIMIT 1
            """,
            (fingerprint,),
        ).fetchone()
        return bool(row)

    def emailed_fingerprints(self) -> set[str]:
        rows = self._conn.execute(
            """
            SELECT DISTINCT fingerprint FROM seen_jobs
            WHERE emailed_at IS NOT NULL
              AND fingerprint IS NOT NULL
              AND fingerprint != ''
            """
        ).fetchall()
        return {str(r["fingerprint"]) for r in rows}

    def has_older_fingerprint(
        self,
        fingerprint: str,
        current_job_id: str,
        *,
        min_age_hours: float = 12.0,
    ) -> bool:
        """
        True if the same (company, title) fingerprint was already recorded under a
        different job_id at least `min_age_hours` ago (catches employers that delete
        and re-create a brand-new LinkedIn job ID for the same role).
        """
        if not fingerprint:
            return False
        rows = self._conn.execute(
            """
            SELECT job_id, first_seen_at FROM seen_jobs
            WHERE fingerprint = ? AND job_id != ?
            """,
            (fingerprint, current_job_id),
        ).fetchall()
        if not rows:
            return False
        cutoff = datetime.now(timezone.utc).timestamp() - (min_age_hours * 3600.0)
        for row in rows:
            try:
                ts = datetime.fromisoformat(
                    str(row["first_seen_at"]).replace("Z", "+00:00")
                )
                if ts.tzinfo is None:
                    ts = ts.replace(tzinfo=timezone.utc)
                if ts.timestamp() <= cutoff:
                    return True
            except ValueError:
                continue
        return False

    def backfill_fingerprints(self) -> int:
        rows = self._conn.execute(
            """
            SELECT job_id, title, company FROM seen_jobs
            WHERE fingerprint IS NULL OR fingerprint = ''
            """
        ).fetchall()
        if not rows:
            return 0
        from src.dedupe import job_fingerprint
        from src.models import Job

        n = 0
        for row in rows:
            fp = job_fingerprint(
                Job(
                    id=row["job_id"],
                    title=row["title"] or "",
                    company=row["company"] or "",
                )
            )
            self._conn.execute(
                "UPDATE seen_jobs SET fingerprint = ? WHERE job_id = ?",
                (fp, row["job_id"]),
            )
            n += 1
        self._conn.commit()
        return n

    def purge_older_than(self, days: int = 7) -> int:
        """Delete rows whose first_seen_at is older than `days`. Returns deleted count."""
        if days <= 0:
            return 0
        cutoff = datetime.now(timezone.utc).timestamp() - (days * 86400)
        rows = self._conn.execute(
            """
            SELECT job_id, first_seen_at, score, emailed_at
            FROM seen_jobs
            """
        ).fetchall()
        to_delete: list[str] = []
        for row in rows:
            # Keep never-emailed high scores so catch-up can still send them
            if row["emailed_at"] is None and row["score"] is not None and row["score"] >= 0.60:
                continue
            try:
                ts = datetime.fromisoformat(
                    str(row["first_seen_at"]).replace("Z", "+00:00")
                )
                if ts.tzinfo is None:
                    ts = ts.replace(tzinfo=timezone.utc)
                if ts.timestamp() < cutoff:
                    to_delete.append(row["job_id"])
            except ValueError:
                # Unparseable timestamp — treat as stale and remove
                to_delete.append(row["job_id"])
        if not to_delete:
            return 0
        self._conn.executemany(
            "DELETE FROM seen_jobs WHERE job_id = ?",
            [(jid,) for jid in to_delete],
        )
        self._conn.commit()
        # Reclaim disk space occasionally
        if len(to_delete) >= 50:
            self._conn.execute("VACUUM")
        return len(to_delete)

    def close(self) -> None:
        self._conn.close()
