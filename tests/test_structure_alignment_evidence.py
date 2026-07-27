"""Public evidence contract for sequence-aware structure alignment."""

import numpy as np
import pytest

from core.run_context import RunContext
from datatypes import (
    Candidate,
    CandidateCollection,
    ProteinStructure,
    StructureAlignment,
)
from modules.structure_align.module import StructureAlignModule
from modules.structure_pairwise_align.module import PairwiseAlignModule


_RESIDUE_NAMES = {
    "A": "ALA",
    "C": "CYS",
    "G": "GLY",
    "S": "SER",
    "T": "THR",
}


def _pdb(
    sequence: str,
    coordinates: list[tuple[float, float, float]],
    *,
    chain: str = "A",
    residue_numbers: list[int] | None = None,
) -> str:
    numbers = residue_numbers or list(range(1, len(sequence) + 1))
    lines = [
        (
            f"ATOM  {serial:5d}  CA  {_RESIDUE_NAMES[amino_acid]:>3s} "
            f"{chain}{residue_number:4d}    "
            f"{x:8.3f}{y:8.3f}{z:8.3f}  1.00  0.00           C"
        )
        for serial, (amino_acid, residue_number, (x, y, z)) in enumerate(
            zip(sequence, numbers, coordinates), start=1
        )
    ]
    return "\n".join([*lines, "END", ""])


def _align(reference_pdb: str, mobile_pdb: str) -> StructureAlignment:
    result = StructureAlignModule().run(
        {
            "reference": ProteinStructure(pdb_string=reference_pdb),
            "mobile": ProteinStructure(pdb_string=mobile_pdb),
        },
        {},
        RunContext("/tmp/test", "alignment"),
    )
    alignment = result["alignment"]
    assert isinstance(alignment, StructureAlignment)
    return alignment


def _pairwise_align(reference_pdb: str, mobile_pdb: str) -> StructureAlignment:
    result = PairwiseAlignModule().run(
        {
            "reference_candidates": CandidateCollection(
                collection_id="reference",
                item_type="protein.structure",
                items=[
                    Candidate(
                        candidate_id="reference-1",
                        data=ProteinStructure(pdb_string=reference_pdb),
                    )
                ],
            ),
            "mobile_candidates": CandidateCollection(
                collection_id="mobile",
                item_type="protein.structure",
                items=[
                    Candidate(
                        candidate_id="mobile-1",
                        data=ProteinStructure(pdb_string=mobile_pdb),
                    )
                ],
            ),
        },
        {},
        RunContext("/tmp/test", "pairwise-alignment"),
    )
    alignment = result["alignments"].items[0].data
    assert isinstance(alignment, StructureAlignment)
    return alignment


def test_identical_structures_expose_complete_reproducible_evidence() -> None:
    coordinates = [(0.0, 0.0, 0.0), (2.0, 1.0, 0.0), (4.0, 0.0, 1.0)]

    alignment = _align(_pdb("AGS", coordinates), _pdb("AGS", coordinates))

    assert alignment.reference_sequence == "AGS"
    assert alignment.mobile_sequence == "AGS"
    assert alignment.reference_length == 3
    assert alignment.mobile_length == 3
    assert alignment.aligned_reference_indices == [0, 1, 2]
    assert alignment.aligned_mobile_indices == [0, 1, 2]
    assert alignment.rmsd == pytest.approx(0.0, abs=1e-12)
    assert alignment.coverage == pytest.approx(1.0)


def test_chain_label_change_preserves_sequence_correspondence_and_provenance() -> None:
    coordinates = [(0.0, 0.0, 0.0), (2.0, 1.0, 0.0), (4.0, 0.0, 1.0)]

    alignment = _align(
        _pdb("AGS", coordinates, chain="A"),
        _pdb("AGS", coordinates, chain="B"),
    )

    assert alignment.residue_map == [
        ("A:1", "B:1"),
        ("A:2", "B:2"),
        ("A:3", "B:3"),
    ]
    assert alignment.chain_map == {"A": "B"}
    assert alignment.aligned_reference_indices == [0, 1, 2]
    assert alignment.aligned_mobile_indices == [0, 1, 2]
    assert alignment.reference_length == 3
    assert alignment.mobile_length == 3
    assert alignment.coverage == pytest.approx(1.0)
    np.testing.assert_allclose(
        alignment.aligned_reference_coordinates,
        coordinates,
    )
    np.testing.assert_allclose(
        alignment.aligned_mobile_coordinates,
        coordinates,
    )
    assert alignment.aligned_distances == pytest.approx([0.0, 0.0, 0.0])


def test_shifted_structure_exposes_a_reproducible_transform_and_distances() -> None:
    reference_coordinates = [
        (0.0, 0.0, 0.0),
        (2.0, 1.0, 0.0),
        (4.0, 0.0, 1.0),
    ]
    shift = np.asarray([5.0, -3.0, 2.0])
    mobile_coordinates = [
        tuple(np.asarray(coordinate) + shift)
        for coordinate in reference_coordinates
    ]

    alignment = _align(
        _pdb("AGS", reference_coordinates),
        _pdb("AGS", mobile_coordinates),
    )

    transformed_mobile = (
        np.asarray(alignment.aligned_mobile_coordinates)
        @ np.asarray(alignment.rotation)
        + np.asarray(alignment.translation)
    )
    reproduced_distances = np.linalg.norm(
        np.asarray(alignment.aligned_reference_coordinates) - transformed_mobile,
        axis=1,
    )

    np.testing.assert_allclose(
        transformed_mobile,
        reference_coordinates,
        atol=1e-12,
    )
    np.testing.assert_allclose(
        alignment.aligned_distances,
        reproduced_distances,
        atol=1e-12,
    )
    assert alignment.rmsd == pytest.approx(
        float(np.sqrt(np.mean(reproduced_distances**2))),
        abs=1e-12,
    )


def test_mobile_insertion_is_skipped_without_shifting_correspondence() -> None:
    reference_coordinates = [
        (0.0, 0.0, 0.0),
        (2.0, 1.0, 0.0),
        (4.0, 0.0, 1.0),
    ]
    mobile_coordinates = [
        reference_coordinates[0],
        (99.0, 99.0, 99.0),
        reference_coordinates[1],
        reference_coordinates[2],
    ]

    alignment = _align(
        _pdb("AGS", reference_coordinates, residue_numbers=[10, 20, 30]),
        _pdb("ACGS", mobile_coordinates, residue_numbers=[1, 2, 3, 4]),
    )

    assert alignment.reference_sequence == "AGS"
    assert alignment.mobile_sequence == "ACGS"
    assert alignment.aligned_reference_indices == [0, 1, 2]
    assert alignment.aligned_mobile_indices == [0, 2, 3]
    assert alignment.residue_map == [
        ("A:10", "A:1"),
        ("A:20", "A:3"),
        ("A:30", "A:4"),
    ]
    assert alignment.coverage == pytest.approx(0.75)
    assert alignment.rmsd == pytest.approx(0.0, abs=1e-12)


def test_repeated_residue_insertion_uses_structure_to_resolve_sequence_tie() -> None:
    reference_coordinates = [
        (0.0, 0.0, 0.0),
        (2.0, 1.0, 0.0),
        (4.0, 0.0, 1.0),
    ]
    mobile_coordinates = [
        *reference_coordinates,
        (99.0, 99.0, 99.0),
    ]

    alignment = _align(
        _pdb("AAA", reference_coordinates),
        _pdb("AAAA", mobile_coordinates),
    )

    assert alignment.aligned_reference_indices == [0, 1, 2]
    assert alignment.aligned_mobile_indices == [0, 1, 2]
    assert alignment.residue_map == [
        ("A:1", "A:1"),
        ("A:2", "A:2"),
        ("A:3", "A:3"),
    ]
    assert alignment.rmsd == pytest.approx(0.0, abs=1e-12)
    assert alignment.coverage == pytest.approx(0.75)


def test_mobile_deletion_is_skipped_without_shifting_correspondence() -> None:
    mobile_coordinates = [
        (0.0, 0.0, 0.0),
        (2.0, 1.0, 0.0),
        (4.0, 0.0, 1.0),
    ]
    reference_coordinates = [
        mobile_coordinates[0],
        (99.0, 99.0, 99.0),
        mobile_coordinates[1],
        mobile_coordinates[2],
    ]

    alignment = _align(
        _pdb("ACGS", reference_coordinates),
        _pdb("AGS", mobile_coordinates),
    )

    assert alignment.aligned_reference_indices == [0, 2, 3]
    assert alignment.aligned_mobile_indices == [0, 1, 2]
    assert alignment.reference_length == 4
    assert alignment.mobile_length == 3
    assert alignment.coverage == pytest.approx(0.75)
    assert alignment.rmsd == pytest.approx(0.0, abs=1e-12)


def test_partial_fragment_reports_alignment_coverage_against_both_lengths() -> None:
    reference_coordinates = [
        (-2.0, 1.0, 0.0),
        (0.0, 0.0, 0.0),
        (2.0, 1.0, 0.0),
        (4.0, 0.0, 1.0),
    ]
    mobile_coordinates = reference_coordinates[1:3]

    alignment = _align(
        _pdb("AGST", reference_coordinates),
        _pdb("GS", mobile_coordinates),
    )

    assert alignment.aligned_reference_indices == [1, 2]
    assert alignment.aligned_mobile_indices == [0, 1]
    assert alignment.reference_length == 4
    assert alignment.mobile_length == 2
    assert len(alignment.aligned_distances) == 2
    assert alignment.coverage == pytest.approx(0.5)


def test_residue_renumbering_changes_only_public_provenance_labels() -> None:
    coordinates = [(0.0, 0.0, 0.0), (2.0, 1.0, 0.0), (4.0, 0.0, 1.0)]

    alignment = _align(
        _pdb("AGS", coordinates, residue_numbers=[1, 2, 3]),
        _pdb("AGS", coordinates, residue_numbers=[101, 205, 999]),
    )

    assert alignment.aligned_reference_indices == [0, 1, 2]
    assert alignment.aligned_mobile_indices == [0, 1, 2]
    assert alignment.residue_map == [
        ("A:1", "A:101"),
        ("A:2", "A:205"),
        ("A:3", "A:999"),
    ]
    assert alignment.rmsd == pytest.approx(0.0, abs=1e-12)


def test_pairwise_module_exposes_the_same_sequence_aware_evidence_contract() -> None:
    reference_coordinates = [
        (0.0, 0.0, 0.0),
        (2.0, 1.0, 0.0),
        (4.0, 0.0, 1.0),
    ]
    mobile_coordinates = [
        reference_coordinates[0],
        (99.0, 99.0, 99.0),
        reference_coordinates[1],
        reference_coordinates[2],
    ]

    alignment = _pairwise_align(
        _pdb("AGS", reference_coordinates, chain="A"),
        _pdb("ACGS", mobile_coordinates, chain="B"),
    )

    assert alignment.aligned_reference_indices == [0, 1, 2]
    assert alignment.aligned_mobile_indices == [0, 2, 3]
    assert alignment.residue_map == [
        ("A:1", "B:1"),
        ("A:2", "B:3"),
        ("A:3", "B:4"),
    ]
    assert alignment.chain_map == {"A": "B"}
    assert alignment.coverage == pytest.approx(0.75)
