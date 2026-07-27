"""Standard reference-normalized TM-score behavior at public Module seams."""

from dataclasses import dataclass
from math import sqrt

import numpy as np
import pytest
from tmtools import tm_align

from core.run_context import RunContext
from datatypes import (
    Candidate,
    CandidateCollection,
    ProteinStructure,
    StructureAlignment,
)
from modules.structure_align.module import StructureAlignModule
from modules.structure_batch_tm_score.module import BatchTMScoreModule
from modules.structure_rmsd.module import StructureRMSDModule
from modules.structure_tm_score.module import StructureTMScoreModule


_RESIDUE_NAMES = {
    "A": "ALA",
    "C": "CYS",
    "G": "GLY",
    "S": "SER",
    "T": "THR",
}
_BASE_COORDINATES = (
    (0.0, 0.0, 0.0),
    (2.0, 1.0, 0.0),
    (4.0, 0.0, 1.0),
    (6.0, 1.0, 0.0),
)


@dataclass(frozen=True)
class _DifferentialCase:
    reference_sequence: str
    reference_coordinates: tuple[tuple[float, float, float], ...]
    mobile_sequence: str
    mobile_coordinates: tuple[tuple[float, float, float], ...]
    fixed_alignment: tuple[str, str]
    reference_chain: str = "A"
    mobile_chain: str = "A"
    reference_numbers: tuple[int, ...] | None = None
    mobile_numbers: tuple[int, ...] | None = None


def _pdb(
    sequence: str,
    coordinates: tuple[tuple[float, float, float], ...],
    *,
    chain: str,
    residue_numbers: tuple[int, ...] | None,
) -> str:
    numbers = residue_numbers or tuple(range(1, len(sequence) + 1))
    lines = [
        (
            f"ATOM  {serial:5d}  CA  {_RESIDUE_NAMES[amino_acid]:>3s} "
            f"{chain}{residue_number:4d}    "
            f"{x:8.3f}{y:8.3f}{z:8.3f}  1.00  0.00           C"
        )
        for serial, (amino_acid, residue_number, (x, y, z)) in enumerate(
            zip(sequence, numbers, coordinates),
            start=1,
        )
    ]
    return "\n".join([*lines, "END", ""])


def _structure_pair(
    case: _DifferentialCase,
) -> tuple[ProteinStructure, ProteinStructure]:
    return (
        ProteinStructure(
            pdb_string=_pdb(
                case.reference_sequence,
                case.reference_coordinates,
                chain=case.reference_chain,
                residue_numbers=case.reference_numbers,
            )
        ),
        ProteinStructure(
            pdb_string=_pdb(
                case.mobile_sequence,
                case.mobile_coordinates,
                chain=case.mobile_chain,
                residue_numbers=case.mobile_numbers,
            )
        ),
    )


def test_single_score_uses_per_residue_distances_and_reference_normalization() -> None:
    reference_coordinates = [
        [-1.0, 0.0, 0.0],
        [1.0, 0.0, 0.0],
        [0.0, -1.0, 0.0],
        [0.0, 1.0, 0.0],
    ]
    mobile_coordinates = [
        [-1.0, 0.0, 0.0],
        [1.0, 0.0, 0.0],
        [0.0, -2.0, 0.0],
        [0.0, 2.0, 0.0],
    ]
    alignment = StructureAlignment(
        residue_map=[
            ("A:1", "B:1"),
            ("A:2", "B:2"),
            ("A:3", "B:3"),
            ("A:4", "B:4"),
        ],
        rmsd=sqrt((0.0**2 + 0.0**2 + 1.0**2 + 1.0**2) / 4),
        coverage=1.0,
        reference_length=4,
        mobile_length=4,
        aligned_reference_indices=[0, 1, 2, 3],
        aligned_mobile_indices=[0, 1, 2, 3],
        aligned_reference_coordinates=reference_coordinates,
        aligned_mobile_coordinates=mobile_coordinates,
        aligned_distances=[0.0, 0.0, 1.0, 1.0],
    )

    result = StructureTMScoreModule().run(
        {"alignment": alignment},
        {},
        RunContext("/tmp/test", "standard-tm-score"),
    )
    score = result["scores"].entries[0]

    # Independent worked example with d0 = 0.5:
    # (1 + 1 + 1/5 + 1/5) / 4 = 0.6.
    assert score.value == pytest.approx(0.6)
    assert score.details == {
        "rmsd": pytest.approx(alignment.rmsd, abs=1e-4),
        "aligned_residues": 4,
        "coverage": 1.0,
        "d0": 0.5,
        "normalization": "reference",
        "normalization_length": 4,
    }


def test_rmsd_reads_the_same_alignment_without_rebuilding_correspondence() -> None:
    alignment = StructureAlignment(
        residue_map=[("A:1", "B:10"), ("A:2", "B:30")],
        rmsd=2.345,
        coverage=0.5,
        reference_length=4,
        mobile_length=2,
        aligned_reference_indices=[0, 1],
        aligned_mobile_indices=[0, 1],
        aligned_distances=[1.0, 3.1622776602],
    )

    result = StructureRMSDModule().run(
        {"alignment": alignment},
        {},
        RunContext("/tmp/test", "shared-alignment-rmsd"),
    )

    assert result["scores"].entries[0].value == pytest.approx(2.345)


def test_collection_score_credits_a_perfect_fragment_by_reference_coverage() -> None:
    alignment = StructureAlignment(
        residue_map=[
            ("A:1", "B:1"),
            ("A:2", "B:2"),
            ("A:3", "B:3"),
        ],
        rmsd=0.0,
        coverage=0.75,
        reference_length=4,
        mobile_length=3,
        aligned_reference_indices=[0, 1, 2],
        aligned_mobile_indices=[0, 1, 2],
        aligned_reference_coordinates=[
            list(coordinate) for coordinate in _BASE_COORDINATES[:3]
        ],
        aligned_mobile_coordinates=[
            list(coordinate) for coordinate in _BASE_COORDINATES[:3]
        ],
        aligned_distances=[0.0, 0.0, 0.0],
    )
    alignments = CandidateCollection(
        collection_id="partial-alignments",
        item_type="structure.alignment",
        items=[Candidate(candidate_id="fragment", data=alignment)],
    )

    result = BatchTMScoreModule().run(
        {"alignments": alignments},
        {"score_id": "tm_vs_3gb1"},
        RunContext("/tmp/test", "batch-standard-tm-score"),
    )
    score = result["scores"].entries[0]

    assert score.score_id == "tm_vs_3gb1"
    assert score.subjects == ["fragment"]
    assert score.value == pytest.approx(0.75)
    assert score.details == {
        "rmsd": 0.0,
        "aligned_residues": 3,
        "coverage": 0.75,
        "d0": 0.5,
        "normalization": "reference",
        "normalization_length": 4,
    }


def test_3gb1_length_controls_scale_and_uncovered_reference_contribution() -> None:
    alignment = StructureAlignment(
        residue_map=[
            ("A:1", "B:1"),
            ("A:2", "B:2"),
            ("A:3", "B:3"),
        ],
        rmsd=0.0,
        coverage=3 / 56,
        reference_length=56,
        mobile_length=3,
        aligned_reference_indices=[0, 1, 2],
        aligned_mobile_indices=[0, 1, 2],
        aligned_reference_coordinates=[
            list(coordinate) for coordinate in _BASE_COORDINATES[:3]
        ],
        aligned_mobile_coordinates=[
            list(coordinate) for coordinate in _BASE_COORDINATES[:3]
        ],
        aligned_distances=[0.0, 0.0, 0.0],
    )

    result = StructureTMScoreModule().run(
        {"alignment": alignment},
        {},
        RunContext("/tmp/test", "3gb1-normalization"),
    )
    score = result["scores"].entries[0]

    assert score.value == pytest.approx(0.0536)
    assert score.details["d0"] == pytest.approx(2.4758)
    assert score.details["coverage"] == pytest.approx(0.0536)
    assert score.details["normalization_length"] == 56


@pytest.mark.parametrize(
    "case",
    [
        pytest.param(
            _DifferentialCase(
                "AGST",
                _BASE_COORDINATES,
                "AGST",
                _BASE_COORDINATES,
                ("AGST", "AGST"),
            ),
            id="identical",
        ),
        pytest.param(
            _DifferentialCase(
                "AGST",
                _BASE_COORDINATES,
                "AGST",
                (*_BASE_COORDINATES[:3], (30.0, 20.0, 10.0)),
                ("AGST", "AGST"),
            ),
            id="strong-outlier",
        ),
        pytest.param(
            _DifferentialCase(
                "AGST",
                _BASE_COORDINATES,
                "AGS",
                _BASE_COORDINATES[:3],
                ("AGST", "AGS-"),
            ),
            id="partial-coverage",
        ),
        pytest.param(
            _DifferentialCase(
                "AGS",
                _BASE_COORDINATES[:3],
                "ACGS",
                (
                    _BASE_COORDINATES[0],
                    (99.0, 99.0, 99.0),
                    _BASE_COORDINATES[1],
                    _BASE_COORDINATES[2],
                ),
                ("A-GS", "ACGS"),
            ),
            id="insertion",
        ),
        pytest.param(
            _DifferentialCase(
                "ACGS",
                (
                    _BASE_COORDINATES[0],
                    (99.0, 99.0, 99.0),
                    _BASE_COORDINATES[1],
                    _BASE_COORDINATES[2],
                ),
                "AGS",
                _BASE_COORDINATES[:3],
                ("ACGS", "A-GS"),
            ),
            id="deletion",
        ),
        pytest.param(
            _DifferentialCase(
                "AGS",
                _BASE_COORDINATES[:3],
                "AGS",
                _BASE_COORDINATES[:3],
                ("AGS", "AGS"),
                reference_numbers=(10, 20, 30),
                mobile_numbers=(101, 205, 999),
            ),
            id="renumbering",
        ),
        pytest.param(
            _DifferentialCase(
                "AGS",
                _BASE_COORDINATES[:3],
                "AGS",
                _BASE_COORDINATES[:3],
                ("AGS", "AGS"),
                reference_chain="A",
                mobile_chain="B",
            ),
            id="chain-change",
        ),
    ],
)
def test_public_scoring_paths_agree_with_trusted_tmtools(
    case: _DifferentialCase,
) -> None:
    reference, mobile = _structure_pair(case)
    alignment = StructureAlignModule().run(
        {"reference": reference, "mobile": mobile},
        {},
        RunContext("/tmp/test", "differential-alignment"),
    )["alignment"]
    assert isinstance(alignment, StructureAlignment)

    trusted = tm_align(
        np.asarray(case.reference_coordinates, dtype=np.float64),
        np.asarray(case.mobile_coordinates, dtype=np.float64),
        case.reference_sequence,
        case.mobile_sequence,
        case.fixed_alignment,
    )
    expected = round(float(trusted.tm_norm_chain1), 4)

    single_score = StructureTMScoreModule().run(
        {"alignment": alignment},
        {},
        RunContext("/tmp/test", "differential-single"),
    )["scores"].entries[0]
    alignment_collection_score = BatchTMScoreModule().run(
        {
            "alignments": CandidateCollection(
                collection_id="alignments",
                item_type="structure.alignment",
                items=[Candidate(candidate_id="candidate", data=alignment)],
            )
        },
        {},
        RunContext("/tmp/test", "differential-alignment-collection"),
    )["scores"].entries[0]
    assert single_score.value == pytest.approx(expected, abs=1e-4)
    assert alignment_collection_score.value == pytest.approx(expected, abs=1e-4)
