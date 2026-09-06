"""
GitHub & DevOps Agent for D.O.N.N.A. (Ported from OpenClaw GitHub Skills Suite)
Enables full GitHub repository control, Pull Request review, Issue management, and CI/CD inspection.
"""

from __future__ import annotations

import os
import sys
import json
import shutil
import subprocess
from pathlib import Path
from typing import Optional, Dict, Any

_OS = sys.platform

def _run_gh(args: list[str]) -> str:
    """Execute gh CLI safely."""
    if not shutil.which("gh"):
        return "GitHub CLI ('gh') is not installed or not in PATH. Run: winget install GitHub.cli"

    try:
        res = subprocess.run(
            ["gh"] + args,
            capture_output=True,
            text=True,
            timeout=20,
            encoding="utf-8",
            errors="ignore",
        )
        if res.returncode != 0:
            err = (res.stderr or "").strip()
            return f"GitHub Error: {err or res.stdout}"
        return (res.stdout or "").strip() or "Success (no output)."
    except Exception as e:
        return f"GitHub CLI execution failed: {e}"


def github_agent(
    parameters: dict = None,
    response=None,
    player=None,
    session_memory=None,
) -> str:
    params = parameters or {}
    action = params.get("action", "list_issues").lower().strip()
    repo   = params.get("repo", "").strip()
    query  = params.get("query", "").strip()
    title  = params.get("title", "").strip()
    body   = params.get("body", "").strip()
    number = str(params.get("number", "")).strip()

    repo_flag = ["--repo", repo] if repo else []

    if action in ("list_issues", "issues"):
        args = ["issue", "list", "--state", "open", "--limit", "10", "--json", "number,title,labels,author"] + repo_flag
        out = _run_gh(args)
        try:
            items = json.loads(out)
            if not items:
                return "No open issues found."
            lines = ["📋 GitHub Issues:"]
            for it in items:
                lines.append(f"- #{it.get('number')}: {it.get('title')} (by @{it.get('author', {}).get('login', 'unknown')})")
            return "\n".join(lines)
        except Exception:
            return out

    if action in ("list_prs", "prs", "pull_requests"):
        args = ["pr", "list", "--state", "open", "--limit", "10", "--json", "number,title,author,headRefName"] + repo_flag
        out = _run_gh(args)
        try:
            items = json.loads(out)
            if not items:
                return "No open pull requests found."
            lines = ["🔀 GitHub Pull Requests:"]
            for it in items:
                lines.append(f"- PR #{it.get('number')}: {it.get('title')} [{it.get('headRefName')}] by @{it.get('author', {}).get('login', 'unknown')}")
            return "\n".join(lines)
        except Exception:
            return out

    if action in ("view_pr", "pr_details"):
        if not number:
            return "Please provide the PR number."
        args = ["pr", "view", number] + repo_flag
        return _run_gh(args)

    if action in ("create_issue", "new_issue"):
        if not title:
            return "Please provide a title for the issue."
        args = ["issue", "create", "--title", title, "--body", body or title] + repo_flag
        return _run_gh(args)

    if action in ("ci_status", "runs", "workflow_status"):
        args = ["run", "list", "--limit", "5", "--json", "databaseId,name,status,conclusion,headBranch"] + repo_flag
        out = _run_gh(args)
        try:
            items = json.loads(out)
            if not items:
                return "No recent workflow runs found."
            lines = ["⚡ GitHub CI/CD Runs:"]
            for it in items:
                conc = it.get('conclusion') or it.get('status')
                lines.append(f"- Run '{it.get('name')}': {conc} on branch '{it.get('headBranch')}'")
            return "\n".join(lines)
        except Exception:
            return out

    if action in ("auth_status", "status"):
        return _run_gh(["auth", "status"])

    return f"Unknown GitHub action: '{action}'. Available: list_issues, list_prs, view_pr, create_issue, ci_status, auth_status."
