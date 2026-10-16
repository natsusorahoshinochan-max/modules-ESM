"""Single synthetic outcome for verifier admission; never collected routinely."""

import os

import pytest


def test_requested_outcome() -> None:
    outcome = os.environ["PROTEIN_WORKBENCH_OUTCOME_PROBE"]
    if outcome == "skipped":
        pytest.skip("synthetic skip to verify zero-skip rejection")
    assert outcome == "passed", "synthetic failure to verify failed-result rejection"
