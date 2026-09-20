"""Fault scenario catalogue (plan section 3). One planted culprit per scenario.

Code/config scenarios carry a `patch` that edits the target repo working
tree; the injector commits it on a fault branch with an innocent-looking
message so the agent has a real diff to find. External scenarios carry
`runtime` changes instead (no commit, no deploy event) because that is what
"not our bug" looks like in reality.
"""

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path


def _replace(rel: str, old: str, new: str) -> Callable[[Path], None]:
    def apply(repo: Path) -> None:
        path = repo / rel
        text = path.read_text(encoding="utf-8")
        if old not in text:
            raise RuntimeError(f"patch anchor not found in {rel}: {old[:60]!r}")
        path.write_text(text.replace(old, new), encoding="utf-8")

    return apply


@dataclass(frozen=True)
class Scenario:
    id: str
    category: str
    title: str
    primary_evidence: list[str] = field(default_factory=list)
    is_external: bool = False
    # code/config change committed on branch fault/<id>
    patch: Callable[[Path], None] | None = None
    commit_message: str = ""
    culprit_path: str | None = None
    # runtime_state rows to set (external / non-git causes)
    runtime: dict[str, str] = field(default_factory=dict)
    # traffic profile hints
    traffic_concurrency: int = 6


SCENARIOS: dict[str, Scenario] = {
    s.id: s
    for s in [
        Scenario(
            id="s01_null_check",
            category="bad_deploy",
            title="Commit removed the null check on shipping_address",
            primary_evidence=["stack trace in logs", "commit diff"],
            patch=_replace(
                "app/routers/checkout.py",
                "    # Store-pickup orders arrive without a shipping address; they must be\n"
                "    # routed through /pickup instead of delivery checkout.\n"
                "    if body.shipping_address is None:\n"
                '        raise HTTPException(400, "shipping_address is required for delivery orders")\n\n',
                "",
            ),
            commit_message="Remove redundant shipping_address validation (client already enforces it)",
            culprit_path="app/routers/checkout.py",
        ),
        Scenario(
            id="s03_pool_exhaustion",
            category="resource_config",
            title="DB connection pool exhaustion after a config change",
            primary_evidence=["db_pool_usage metric", "config diff"],
            patch=_replace(
                "app/config.py",
                "    db_pool_size: int = 10\n    db_max_overflow: int = 5\n"
                "    db_pool_timeout_seconds: int = 3\n",
                "    db_pool_size: int = 1\n    db_max_overflow: int = 0\n"
                "    db_pool_timeout_seconds: int = 1\n",
            ),
            commit_message="Reduce DB pool size and fail fast on pool wait (shared instance limits)",
            culprit_path="app/config.py",
            traffic_concurrency=12,
        ),
        Scenario(
            id="s08_provider_outage",
            category="external",
            title="Payment provider outage (not our bug)",
            primary_evidence=["upstream timeouts in logs", "no recent deploy"],
            is_external=True,
            runtime={"payment_provider_status": "down"},
        ),
        # --- later phases -------------------------------------------------
        Scenario("s02_column_rename", "schema_change", "Migration renamed a column still in use",
                 ["SQL errors", "migration file"]),
        Scenario("s04_rotated_key", "config_secret", "Expired or rotated third-party API key",
                 ["401s from provider in logs"],
                 runtime={"payment_provider_expected_api_key": "pk_live_ROTATED"}),
        Scenario("s05_n_plus_one", "performance", "N+1 query introduced, causing timeouts",
                 ["query counts", "latency", "diff"]),
        Scenario("s06_dependency_bump", "dependency", "Dependency bump changed a serialization format",
                 ["lockfile diff", "parse errors"]),
        Scenario("s07_feature_flag", "config", "Feature flag misconfigured for one region",
                 ["errors clustered by region"]),
        Scenario("s09_missing_index", "performance", "Missing index after a migration",
                 ["slow query log", "EXPLAIN"]),
        Scenario("s10_race_condition", "concurrency", "Race condition on inventory decrement",
                 ["negative stock rows", "intermittent"]),
    ]
}

PHASE_1_SCENARIOS = ["s01_null_check", "s03_pool_exhaustion", "s08_provider_outage"]


def is_implemented(s: Scenario) -> bool:
    return s.patch is not None or bool(s.runtime)
