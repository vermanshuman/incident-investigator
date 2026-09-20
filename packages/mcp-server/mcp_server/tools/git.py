import subprocess
from datetime import UTC, datetime, timedelta

from pydantic import BaseModel, Field

from mcp_server.config import get_settings


class CommitInfo(BaseModel):
    sha: str
    short_sha: str
    author: str
    ts: str
    message: str
    files_changed: list[str]
    is_head: bool = Field(description="True for the commit currently deployed")


class CommitDiff(BaseModel):
    sha: str
    author: str
    ts: str
    message: str
    path: str | None
    diff: str
    truncated: bool


class GitError(RuntimeError):
    pass


def _git(*args: str) -> str:
    repo = get_settings().target_repo_path
    r = subprocess.run(["git", "-C", repo, *args], capture_output=True, text=True, check=False)
    if r.returncode != 0:
        raise GitError(r.stderr.strip() or f"git {' '.join(args)} failed")
    return r.stdout


SEP = "\x1f"
REC = "\x1e"


def list_commits(
    start: str | None = None,
    end: str | None = None,
    paths: list[str] | None = None,
    author: str | None = None,
    limit: int = 30,
) -> list[CommitInfo]:
    """List commits on the deployed branch of the target repo, newest first.
    `start`/`end` are ISO timestamps (default: last 7 days); `paths` restricts
    to commits touching those files/dirs; `author` filters by name/email.
    The first result with is_head=True is the code currently running."""
    now = datetime.now(UTC)
    since = start or (now - timedelta(days=7)).isoformat()
    args = [
        "log", "HEAD", f"--since={since}", "--name-only",
        f"--format={REC}%H{SEP}%an{SEP}%aI{SEP}%s", f"--max-count={max(1, min(limit, 100))}",
    ]
    if end:
        args.append(f"--until={end}")
    if author:
        args.append(f"--author={author}")
    if paths:
        args += ["--", *paths]
    out = _git(*args)
    head = _git("rev-parse", "HEAD").strip()

    commits = []
    for rec in out.split(REC):
        if not rec.strip():
            continue
        header, _, files = rec.partition("\n")
        sha, an, ts, msg = header.split(SEP)
        commits.append(
            CommitInfo(
                sha=sha, short_sha=sha[:8], author=an, ts=ts, message=msg,
                files_changed=[f for f in files.splitlines() if f.strip()],
                is_head=(sha == head),
            )
        )
    return commits


def get_commit_diff(sha: str, path: str | None = None) -> CommitDiff:
    """Show what a commit changed (unified diff, size-limited). Pass `path` to
    restrict the diff to one file."""
    max_bytes = get_settings().max_diff_bytes
    header = _git("show", "-s", f"--format=%H{SEP}%an{SEP}%aI{SEP}%s", sha).strip()
    full_sha, an, ts, msg = header.split(SEP)
    args = ["show", "--format=", "--no-color", sha]
    if path:
        args += ["--", path]
    diff = _git(*args)
    truncated = len(diff) > max_bytes
    return CommitDiff(
        sha=full_sha, author=an, ts=ts, message=msg, path=path,
        diff=diff[:max_bytes] + ("\n... [truncated]" if truncated else ""), truncated=truncated,
    )
