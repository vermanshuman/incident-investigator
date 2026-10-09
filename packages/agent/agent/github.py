"""The one write action: open a GitHub issue for an approved report.

Deliberately not an MCP tool. The agent cannot reach this - it runs after a
human approves, from the trusted side, and the token never enters a prompt.

GITHUB_TOKEN  a token with `issues: write` on the target repo only
GITHUB_REPO   owner/name
"""

from __future__ import annotations

import os

import httpx

API = "https://api.github.com"
TIMEOUT = 15.0


class GitHubError(RuntimeError):
    pass


def is_configured() -> bool:
    return bool(os.getenv("GITHUB_TOKEN") and os.getenv("GITHUB_REPO"))


def _repo() -> str:
    repo = os.getenv("GITHUB_REPO", "")
    if repo.count("/") != 1:
        raise GitHubError(f"GITHUB_REPO must be owner/name, got {repo!r}")
    return repo


def create_issue(title: str, body: str, labels: list[str] | None = None,
                 dry_run: bool = False) -> dict:
    """Open an issue and return {url, number, dry_run}.

    `dry_run` renders what would be posted without calling GitHub, which is
    how the demo shows the approval flow without a token.
    """
    if dry_run or not is_configured():
        return {"url": None, "number": None, "dry_run": True,
                "reason": "GITHUB_TOKEN/GITHUB_REPO not set" if not is_configured() else "requested"}

    response = httpx.post(
        f"{API}/repos/{_repo()}/issues",
        headers={
            "Authorization": f"Bearer {os.environ['GITHUB_TOKEN']}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        },
        json={"title": title[:250], "body": body, "labels": labels or ["incident", "ai-investigated"]},
        timeout=TIMEOUT,
    )
    if response.status_code >= 300:
        # Never echo the token; surface GitHub's own message.
        raise GitHubError(f"GitHub returned {response.status_code}: {response.text[:300]}")
    data = response.json()
    return {"url": data["html_url"], "number": data["number"], "dry_run": False}
