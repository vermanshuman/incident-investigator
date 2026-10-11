from pathlib import Path

from faults import repo as repo_ops
from faults.scenarios import REPRODUCIBLE, SCENARIOS, is_implemented


def test_every_reproducible_scenario_is_implemented():
    for sid in REPRODUCIBLE:
        assert is_implemented(SCENARIOS[sid]), sid


def test_the_catalogue_covers_distinct_categories():
    """A suite that only contains bad deploys proves nothing."""
    categories = {SCENARIOS[s].category for s in REPRODUCIBLE}
    assert {"bad_deploy", "external", "config", "config_secret", "performance"} <= categories


def test_patches_apply_to_the_current_source(tmp_path):
    """A patch anchor that has drifted must fail loudly, not silently no-op."""
    from faults import repo as repo_ops

    repo = tmp_path / "repo"
    repo_ops.seed_repo(repo)
    for sid in REPRODUCIBLE:
        s = SCENARIOS[sid]
        if s.patch is None:
            continue
        sha = repo_ops.commit_on_branch(repo, f"fault/{s.id}", s.commit_message, ("a", "a@x"), s.patch)
        assert s.culprit_path in repo_ops.git(repo, "show", "--stat", sha)
        repo_ops.checkout_main(repo)


def test_seed_repo_and_patch(tmp_path: Path):
    repo = tmp_path / "repo"
    repo_ops.seed_repo(repo)
    assert int(repo_ops.git(repo, "rev-list", "--count", "HEAD")) >= 25

    s = SCENARIOS["s01_null_check"]
    sha = repo_ops.commit_on_branch(repo, f"fault/{s.id}", s.commit_message, ("a", "a@x"), s.patch)
    diff = repo_ops.git(repo, "show", "--stat", sha)
    assert "app/routers/checkout.py" in diff
    assert "shipping_address is None" not in (repo / "app/routers/checkout.py").read_text()

    repo_ops.checkout_main(repo)
    assert "shipping_address is None" in (repo / "app/routers/checkout.py").read_text()


def test_drift_from_the_source_is_detected(tmp_path):
    """A seeded repo that no longer matches app/ must be spotted, because the
    scenario patches silently stop applying."""
    from faults import repo as repo_ops

    repo = tmp_path / "repo"
    repo_ops.seed_repo(repo)
    assert repo_ops.matches_source(repo)

    (repo / "app" / "config.py").write_text("# someone edited the service\n", encoding="utf-8")
    assert not repo_ops.matches_source(repo)
    assert not repo_ops.matches_source(tmp_path / "never-seeded")
