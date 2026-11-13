"""Sync data/seen_jobs.db between local MacBook runs and GitHub Actions via origin/job-state."""

from __future__ import annotations

import os
import subprocess
import tempfile
from pathlib import Path

from src.db import JobDB

STATE_BRANCH = "job-state"
DB_REL_PATH = "data/seen_jobs.db"


def pull_and_merge_remote_state(root: Path, db: JobDB) -> int:
    """
    Fetch `origin/job-state` (if reachable) and merge its `seen_jobs` rows into `db`
    without touching the current git branch or working tree.
    """
    try:
        res = subprocess.run(
            ["git", "fetch", "origin", STATE_BRANCH, "--depth=1"],
            cwd=root,
            capture_output=True,
            text=True,
            timeout=20,
        )
        if res.returncode != 0:
            return 0

        blob = subprocess.run(
            ["git", "show", f"FETCH_HEAD:{DB_REL_PATH}"],
            cwd=root,
            capture_output=True,
            timeout=15,
        )
        if blob.returncode != 0 or not blob.stdout:
            return 0

        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
            tmp.write(blob.stdout)
            tmp_path = Path(tmp.name)

        try:
            merged = db.merge_from(tmp_path)
            if merged:
                print(f"State sync: merged {merged} rows from origin/{STATE_BRANCH}")
            return merged
        finally:
            tmp_path.unlink(missing_ok=True)
    except Exception as exc:  # noqa: BLE001
        print(f"State sync pull skipped: {exc}")
        return 0


def push_remote_state(root: Path, db_path: Path) -> bool:
    """
    Push `data/seen_jobs.db` to `origin/job-state` using git plumbing commands so the
    current branch (`main`) and working tree are never modified or switched.
    """
    if not db_path.exists():
        return False
    try:
        blob_res = subprocess.run(
            ["git", "hash-object", "-w", str(db_path)],
            cwd=root,
            capture_output=True,
            text=True,
            timeout=15,
            check=True,
        )
        blob_sha = blob_res.stdout.strip()

        sub_tree_input = f"100644 blob {blob_sha}\tseen_jobs.db\n"
        sub_tree_res = subprocess.run(
            ["git", "mktree"],
            cwd=root,
            input=sub_tree_input,
            capture_output=True,
            text=True,
            timeout=15,
            check=True,
        )
        sub_tree_sha = sub_tree_res.stdout.strip()

        root_tree_input = f"040000 tree {sub_tree_sha}\tdata\n"
        root_tree_res = subprocess.run(
            ["git", "mktree"],
            cwd=root,
            input=root_tree_input,
            capture_output=True,
            text=True,
            timeout=15,
            check=True,
        )
        root_tree_sha = root_tree_res.stdout.strip()

        env = {
            **os.environ,
            "GIT_AUTHOR_NAME": "job-email-sync",
            "GIT_AUTHOR_EMAIL": "41898282+github-actions[bot]@users.noreply.github.com",
            "GIT_COMMITTER_NAME": "job-email-sync",
            "GIT_COMMITTER_EMAIL": "41898282+github-actions[bot]@users.noreply.github.com",
        }
        commit_res = subprocess.run(
            ["git", "commit-tree", root_tree_sha, "-m", "chore(state): sync seen_jobs.db"],
            cwd=root,
            env=env,
            capture_output=True,
            text=True,
            timeout=15,
            check=True,
        )
        commit_sha = commit_res.stdout.strip()

        push_res = subprocess.run(
            ["git", "push", "--force", "origin", f"{commit_sha}:refs/heads/{STATE_BRANCH}"],
            cwd=root,
            capture_output=True,
            text=True,
            timeout=25,
        )
        if push_res.returncode == 0:
            print(f"State sync: pushed {DB_REL_PATH} to origin/{STATE_BRANCH}")
            return True
        return False
    except Exception as exc:  # noqa: BLE001
        print(f"State sync push skipped: {exc}")
        return False
