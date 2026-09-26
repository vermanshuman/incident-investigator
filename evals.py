"""Run the eval suite: inject each scenario, investigate, score.

    python evals.py
    python evals.py --only s01_null_check_v1
"""

from _local import main

main("evals", "run-evals")
