from pathlib import Path

from faults import repo as repo_ops
from faults.scenarios import PHASE_1_SCENARIOS, SCENARIOS, is_implemented


def test_phase1_scenarios_implemented():
    for sid in PHASE_1_SCENARIOS:
        assert is_implemented(SCENARIOS[sid])


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
