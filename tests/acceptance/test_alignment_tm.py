"""Acceptance: local structural alignment and TM-score boundaries."""

import pytest

from modules.structure_alignment import align_structures
from modules.structure_tm_score.scoring import (
    calculate_reference_normalized_tm_score,
)
from tests.acceptance.conftest import require_ready


@pytest.mark.acceptance
@pytest.mark.local_provider
def test_real_alignment_and_tm_score(
    readiness,
    pdb_3gb1,
    pdb_1pga,
):
    require_ready("alignment", readiness)

    alignment = align_structures(pdb_3gb1, pdb_1pga)
    score = calculate_reference_normalized_tm_score(alignment)
    assert len(alignment.residue_map) > 0
    assert 0.0 <= score.value <= 1.0
