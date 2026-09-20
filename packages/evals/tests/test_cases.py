from evals.cases import load_cases


def test_cases_load_and_include_an_external_one():
    cases = load_cases()
    assert len(cases) >= 3
    assert any(c.ground_truth.is_external for c in cases)
