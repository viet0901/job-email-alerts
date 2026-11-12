from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class Job:
    id: str
    title: str
    company: str
    location: str = ""
    work_model: str = ""
    apply_url: str = ""
    qualifications: str = ""
    h1b_sponsored: str | None = None  # Yes | No | Not Sure | None
    salary: str = ""
    category: str = ""
    source: str = "jobright"
    posted_date_ms: int | None = None  # true first-publish / created time
    updated_date_ms: int | None = None  # ATS last-updated (Greenhouse bumps this)
    is_reposted: bool = False  # LinkedIn "Reposted X ago" / ATS bump, not a new job
    original_posted_date_ms: int | None = None  # LinkedIn originalListedAt when known
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def text_blob(self) -> str:
        parts = [self.title, self.company, self.location, self.qualifications]
        return "\n".join(p for p in parts if p)
