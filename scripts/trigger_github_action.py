#!/usr/bin/env python3
"""Trigger the GitHub Actions workflow via workflow_dispatch using local git credentials."""

from __future__ import annotations

import os
import subprocess
import sys
import requests

REPO = "viet0901/job-email-alerts"
WORKFLOW_FILE = "job_alerts.yml"


def _get_github_token() -> str:
    env_tok = os.getenv("GITHUB_TOKEN", "").strip()
    if env_tok:
        return env_tok
    proc = subprocess.run(
        ["git", "credential", "fill"],
        input="protocol=https\nhost=github.com\n\n",
        text=True,
        capture_output=True,
        timeout=10,
        check=False,
    )
    for line in proc.stdout.splitlines():
        if line.startswith("password="):
            return line.split("=", 1)[1].strip()
    return ""


def main() -> int:
    token = _get_github_token()
    if not token:
        print("No GitHub token found in env or git credential store.")
        return 1

    url = f"https://api.github.com/repos/{REPO}/actions/workflows/{WORKFLOW_FILE}/dispatches"
    resp = requests.post(
        url,
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "User-Agent": "job-email-mac-dispatcher",
        },
        json={"ref": "main", "inputs": {"mode": "live"}},
        timeout=15,
    )
    if resp.status_code == 204:
        print(f"Triggered GitHub Action ({WORKFLOW_FILE}) on {REPO} -> 204 No Content")
        return 0
    print(f"GitHub dispatch returned {resp.status_code}: {resp.text[:200]}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
