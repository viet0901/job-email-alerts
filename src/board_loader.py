"""Load direct company ATS boards from ats_boards.yaml and merge with config."""

from __future__ import annotations

from pathlib import Path
from typing import Any


def load_ats_boards(root: Path, config: dict[str, Any]) -> dict[str, list]:
    rel = config.get("ats_boards_file") or "ats_boards.yaml"
    path = Path(rel)
    if not path.is_absolute():
        path = root / path
    if not path.exists():
        return {}
    import yaml

    with path.open(encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    if not isinstance(data, dict):
        return {}
    return {k: list(v or []) for k, v in data.items() if isinstance(v, list)}


def boards_for(sources: dict, ats: dict[str, list], key: str) -> list:
    """Prefer explicit config boards; otherwise use the shared ATS catalog."""
    cfg = sources.get(key) or {}
    inline = list(cfg.get("boards") or [])
    catalog = list(ats.get(key) or [])
    if inline:
        return _merge_unique(catalog, inline) if cfg.get("merge_catalog", True) else inline
    return catalog


def _entry_key(entry: dict | str) -> str:
    if isinstance(entry, str):
        return entry.strip().lower()
    token = str(entry.get("token") or "").strip().lower()
    query = str(entry.get("query") or "").strip().lower()
    host = str(entry.get("host") or "").strip().lower()
    site = str(entry.get("site") or "").strip().lower()
    if host:
        return f"{host}/{site}"
    if token:
        return f"{token}|{query}"
    return ""


def _merge_unique(catalog: list, inline: list) -> list:
    seen: set[str] = set()
    out: list = []
    for entry in list(inline) + list(catalog):
        token = _entry_key(entry)
        if not token or token in seen:
            continue
        seen.add(token)
        out.append(entry)
    return out
