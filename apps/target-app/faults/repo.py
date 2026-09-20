"""Seed the target git repository with a believable commit history.

The repo is a copy of apps/target-app (app/ + pyproject) built up over ~30
commits spread across the last 45 days by a small team. The final tree equals
the current source. Fault branches are created later by the injector.
"""

import os
import random
import shutil
import subprocess
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path

SRC_ROOT = Path(__file__).resolve().parents[1]  # apps/target-app

AUTHORS = [
    ("Priya Nair", "priya@example.com"),
    ("Rahul Mehta", "rahul@example.com"),
    ("Sam Okoro", "sam@example.com"),
    ("Lena Fischer", "lena@example.com"),
]

# Earlier versions of lines that later commits change. Applied in reverse so
# the first commit of a file contains the *old* value.
EDITS = {
    "shipping_fee": ("app/config.py", "shipping_fee_international: float = 15.0", "shipping_fee_international: float = 12.0"),
    "pool_size": ("app/config.py", "db_pool_size: int = 10", "db_pool_size: int = 5"),
    "provider_timeout": ("app/config.py", "payment_provider_timeout_seconds: float = 2.0", "payment_provider_timeout_seconds: float = 5.0"),
    "free_shipping": ("app/config.py", "free_shipping_threshold: float = 999.0", "free_shipping_threshold: float = 1499.0"),
    "catalogue": ("app/seed.py", '    ("SKU-005", "Webcam 1080p", 2199.0),\n    ("SKU-006", "Desk Lamp", 899.0),\n', ""),
    "stock": ("app/seed.py", "stock=500", "stock=100"),
    "sample_interval": ("app/config.py", "metrics_sample_interval_seconds: int = 5", "metrics_sample_interval_seconds: int = 15"),
}

# (message, files added at this step, edits reverted to their FINAL value at this step)
HISTORY: list[tuple[str, list[str], list[str]]] = [
    ("Initial commit: checkout service skeleton", ["README.md", "pyproject.toml", "app/__init__.py"], []),
    ("Add settings module", ["app/config.py"], []),
    ("Add SQLAlchemy engine with pooled connections", ["app/db.py"], []),
    ("Add product, cart and order models", ["app/models.py"], []),
    ("Seed initial product catalogue", ["app/seed.py"], []),
    ("Add cart endpoints", ["app/routers/__init__.py", "app/routers/cart.py"], []),
    ("Add structured JSON request logging", ["app/logging.py"], []),
    ("Add checkout endpoint with inventory reservation", ["app/routers/checkout.py"], []),
    ("Integrate payment provider client", ["app/provider.py"], []),
    ("Add payment retry endpoint", ["app/routers/payment.py"], []),
    ("Wire up FastAPI app with lifespan and health", ["app/main.py"], []),
    ("Persist logs to app_logs table for observability", [], []),
    ("Add metrics sampler (request rate, error rate, p95)", ["app/metrics.py"], []),
    ("Raise stock levels for launch", [], ["stock"]),
    ("Add unit tests for checkout", ["tests/__init__.py", "tests/test_checkout.py"], []),
    ("Tighten payment provider timeout to 2s", [], ["provider_timeout"]),
    ("Fix rounding on order totals", [], []),
    ("Increase DB pool size to 10 for peak traffic", [], ["pool_size"]),
    ("Add region header to request logs", [], []),
    ("Raise international shipping fee to 15", [], ["shipping_fee"]),
    ("Add new SKUs for autumn catalogue", [], ["catalogue"]),
    ("Expose db pool usage in metrics", [], []),
    ("Lower free shipping threshold to 999", [], ["free_shipping"]),
    ("Sample metrics every 5s instead of 15s", [], ["sample_interval"]),
    ("Return 409 on insufficient stock", [], []),
    ("Log provider errors with order id", [], []),
    ("Add trace id propagation from x-trace-id header", [], []),
    ("Refactor shipping fee calculation", [], []),
    ("Update README with local run instructions", [], []),
    ("Bump version to 0.1.0", [], []),
]

TRACKED_FILES = [
    "README.md", "pyproject.toml", "app/__init__.py", "app/config.py", "app/db.py",
    "app/models.py", "app/seed.py", "app/routers/__init__.py", "app/routers/cart.py",
    "app/logging.py", "app/routers/checkout.py", "app/provider.py", "app/routers/payment.py",
    "app/main.py", "app/metrics.py", "tests/__init__.py", "tests/test_checkout.py",
]


def git(repo: Path, *args: str, env: dict | None = None) -> str:
    r = subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True, env=env, check=False)
    if r.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed: {r.stderr.strip()}")
    return r.stdout.strip()


def _final_content(rel: str) -> str:
    if rel == "README.md":
        return "# checkout-service\n\nCart, checkout and payment API.\n\n```\nuvicorn app.main:app --port 8080\n```\n"
    return (SRC_ROOT / rel).read_text(encoding="utf-8")


def _content_at_step(rel: str, applied_edits: set[str]) -> str:
    text = _final_content(rel)
    for name, (path, final, earlier) in EDITS.items():
        if path == rel and name not in applied_edits and final in text:
            text = text.replace(final, earlier)
    return text


def seed_repo(repo: Path, force: bool = False) -> None:
    if repo.exists():
        if not force:
            return
        shutil.rmtree(repo, onerror=lambda f, p, _: (os.chmod(p, 0o777), f(p)))
    repo.mkdir(parents=True)
    git(repo, "init", "-q", "-b", "main")
    git(repo, "config", "user.name", "seed")
    git(repo, "config", "user.email", "seed@example.com")
    (repo / ".gitignore").write_text("__pycache__/\n*.pyc\ndata/\n.venv/\n")

    rng = random.Random(42)
    now = datetime.now(UTC)
    start = now - timedelta(days=45)
    step = timedelta(days=45) / len(HISTORY)
    present: list[str] = []
    applied: set[str] = set()

    for i, (message, new_files, edits) in enumerate(HISTORY):
        present += new_files
        applied |= set(edits)
        for rel in present:
            path = repo / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(_content_at_step(rel, applied), encoding="utf-8")
        ts = start + step * i + timedelta(minutes=rng.randint(0, 600))
        name, email = rng.choice(AUTHORS)
        env = {
            **os.environ,
            "GIT_AUTHOR_NAME": name, "GIT_AUTHOR_EMAIL": email,
            "GIT_COMMITTER_NAME": name, "GIT_COMMITTER_EMAIL": email,
            "GIT_AUTHOR_DATE": ts.isoformat(), "GIT_COMMITTER_DATE": ts.isoformat(),
        }
        git(repo, "add", "-A")
        git(repo, "commit", "-q", "--allow-empty", "-m", message, env=env)

    # Sanity: the final tree must equal the current source.
    for rel in TRACKED_FILES:
        if rel != "README.md" and (repo / rel).read_text(encoding="utf-8") != _final_content(rel):
            raise RuntimeError(f"seeded repo differs from source for {rel}")


def commit_on_branch(
    repo: Path, branch: str, message: str, author: tuple[str, str], apply: Callable[[Path], None]
) -> str:
    """Branch from main, apply the patch to the working tree, commit; return the SHA."""
    git(repo, "checkout", "-q", "main")
    if branch in git(repo, "branch", "--list", branch):
        git(repo, "branch", "-q", "-D", branch)
    git(repo, "checkout", "-q", "-b", branch)
    apply(repo)
    name, email = author
    env = {**os.environ, "GIT_AUTHOR_NAME": name, "GIT_AUTHOR_EMAIL": email,
           "GIT_COMMITTER_NAME": name, "GIT_COMMITTER_EMAIL": email}
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", message, env=env)
    return git(repo, "rev-parse", "HEAD")


def checkout_main(repo: Path) -> None:
    git(repo, "checkout", "-q", "--", ".")
    git(repo, "checkout", "-q", "main")
    for b in git(repo, "branch", "--list", "fault/*").split():
        if b != "*":
            git(repo, "branch", "-q", "-D", b)
