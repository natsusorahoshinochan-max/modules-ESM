"""Shared sequence-aware CA alignment used by structure alignment Modules."""

from collections import Counter
from dataclasses import dataclass
from importlib.metadata import version

import numpy as np
from Bio.Align import PairwiseAligner, substitution_matrices
from Bio.SVDSuperimposer import SVDSuperimposer

from datatypes import ProteinStructure, StructureAlignment


_AA_3TO1 = {
    "ALA": "A",
    "ARG": "R",
    "ASN": "N",
    "ASP": "D",
    "CYS": "C",
    "GLN": "Q",
    "GLU": "E",
    "GLY": "G",
    "HIS": "H",
    "ILE": "I",
    "LEU": "L",
    "LYS": "K",
    "MET": "M",
    "PHE": "F",
    "PRO": "P",
    "SER": "S",
    "THR": "T",
    "TRP": "W",
    "TYR": "Y",
    "VAL": "V",
}
_SEQUENCE_GAP_OPEN_SCORE = -3.0
_SEQUENCE_GAP_EXTEND_SCORE = -0.5
_SEQUENCE_END_GAP_OPEN_SCORE = -2.0
_SEQUENCE_END_GAP_EXTEND_SCORE = -0.5
_MAX_EXHAUSTIVE_SEQUENCE_ALIGNMENTS = 1024


def _record_alignment_evidence(
    alignment: StructureAlignment,
) -> StructureAlignment:
    from core.provider_evidence import record_provider_call_result

    record_provider_call_result(
        provider="biopython-svd",
        operation="structure_align",
        model="PairwiseAligner+SVDSuperimposer",
        provider_identity={
            "biopython_version": version("biopython"),
            "numpy_version": version("numpy"),
        },
        effective_seed=None,
        seed_control="deterministic_no_rng",
        result_summary={
            "reference_length": alignment.reference_length,
            "mobile_length": alignment.mobile_length,
            "aligned_residues": len(alignment.residue_map),
            "rmsd": float(alignment.rmsd),
            "coverage": float(alignment.coverage),
        },
    )
    return alignment


@dataclass(frozen=True)
class _ResidueCA:
    amino_acid: str
    chain: str
    residue_number: str
    insertion_code: str
    coordinate: tuple[float, float, float]

    @property
    def pdb_label(self) -> str:
        return f"{self.chain}:{self.residue_number}{self.insertion_code}"


def _superimpose(
    reference_coordinates: np.ndarray,
    mobile_coordinates: np.ndarray,
) -> SVDSuperimposer:
    superimposer = SVDSuperimposer()
    superimposer.set(reference_coordinates, mobile_coordinates)
    superimposer.run()
    return superimposer


def _parse_pdb_ca(pdb_string: str) -> list[_ResidueCA]:
    """Extract one sequence-ordered CA record per PDB residue."""
    residues: list[_ResidueCA] = []
    seen: set[tuple[str, str, str]] = set()

    for line in pdb_string.splitlines():
        if not (line.startswith("ATOM") or line.startswith("HETATM")):
            continue
        if line[12:16].strip() != "CA":
            continue
        alternate_location = line[16:17]
        if alternate_location not in {" ", "A"}:
            continue

        chain = line[21:22].strip()
        residue_number = line[22:26].strip()
        insertion_code = line[26:27].strip()
        residue_key = (chain, residue_number, insertion_code)
        if residue_key in seen:
            continue

        try:
            coordinate = (
                float(line[30:38]),
                float(line[38:46]),
                float(line[46:54]),
            )
        except ValueError:
            continue

        residues.append(
            _ResidueCA(
                amino_acid=_AA_3TO1.get(line[17:20].strip().upper(), "X"),
                chain=chain,
                residue_number=residue_number,
                insertion_code=insertion_code,
                coordinate=coordinate,
            )
        )
        seen.add(residue_key)

    return residues


def _sequence_correspondence(
    reference_sequence: str,
    mobile_sequence: str,
    reference_coordinates: np.ndarray,
    mobile_coordinates: np.ndarray,
) -> tuple[list[int], list[int]]:
    """Return sequence-optimal pairs with structure-aware tie resolution."""
    aligner = PairwiseAligner(mode="global")
    aligner.substitution_matrix = substitution_matrices.load("BLOSUM62")
    aligner.open_gap_score = _SEQUENCE_GAP_OPEN_SCORE
    aligner.extend_gap_score = _SEQUENCE_GAP_EXTEND_SCORE
    if hasattr(aligner, "open_end_gap_score"):
        aligner.open_end_gap_score = _SEQUENCE_END_GAP_OPEN_SCORE
        aligner.extend_end_gap_score = _SEQUENCE_END_GAP_EXTEND_SCORE
    else:
        aligner.end_open_gap_score = _SEQUENCE_END_GAP_OPEN_SCORE
        aligner.end_extend_gap_score = _SEQUENCE_END_GAP_EXTEND_SCORE
    sequence_alignments = aligner.align(reference_sequence, mobile_sequence)

    try:
        alignment_count = len(sequence_alignments)
    except OverflowError:
        alignment_count = _MAX_EXHAUSTIVE_SEQUENCE_ALIGNMENTS + 1

    if (
        alignment_count > _MAX_EXHAUSTIVE_SEQUENCE_ALIGNMENTS
        and min(len(reference_sequence), len(mobile_sequence)) >= 3
    ):
        from tmtools import tm_align

        structural_alignment = tm_align(
            reference_coordinates,
            mobile_coordinates,
            reference_sequence,
            mobile_sequence,
        )
        reference_indices: list[int] = []
        mobile_indices: list[int] = []
        reference_index = -1
        mobile_index = -1
        for reference_amino_acid, mobile_amino_acid in zip(
            structural_alignment.seqxA,
            structural_alignment.seqyA,
        ):
            if reference_amino_acid != "-":
                reference_index += 1
            if mobile_amino_acid != "-":
                mobile_index += 1
            if reference_amino_acid != "-" and mobile_amino_acid != "-":
                reference_indices.append(reference_index)
                mobile_indices.append(mobile_index)
        return reference_indices, mobile_indices

    best_correspondence: tuple[list[int], list[int]] | None = None
    best_key: tuple[int, float, tuple[int, ...], tuple[int, ...]] | None = None
    for alignment in sequence_alignments:
        paired_indices = [
            (int(reference_index), int(mobile_index))
            for reference_index, mobile_index in zip(*alignment.indices)
            if reference_index >= 0 and mobile_index >= 0
        ]
        reference_indices = [
            reference_index for reference_index, _ in paired_indices
        ]
        mobile_indices = [mobile_index for _, mobile_index in paired_indices]
        if reference_indices:
            superimposer = _superimpose(
                reference_coordinates[reference_indices],
                mobile_coordinates[mobile_indices],
            )
            fit_rmsd = float(superimposer.get_rms())
        else:
            fit_rmsd = float("inf")
        key = (
            -len(reference_indices),
            fit_rmsd,
            tuple(reference_indices),
            tuple(mobile_indices),
        )
        if best_key is None or key < best_key:
            best_key = key
            best_correspondence = (reference_indices, mobile_indices)

    if best_correspondence is None:
        return [], []
    return best_correspondence


def _chain_map(
    reference_residues: list[_ResidueCA],
    mobile_residues: list[_ResidueCA],
    reference_indices: list[int],
    mobile_indices: list[int],
) -> dict[str, str]:
    """Infer each reference chain's dominant corresponding mobile chain."""
    correspondences: dict[str, Counter[str]] = {}
    for reference_index, mobile_index in zip(reference_indices, mobile_indices):
        reference_chain = reference_residues[reference_index].chain
        mobile_chain = mobile_residues[mobile_index].chain
        correspondences.setdefault(reference_chain, Counter())[mobile_chain] += 1

    return {
        reference_chain: min(
            mobile_counts,
            key=lambda mobile_chain: (-mobile_counts[mobile_chain], mobile_chain),
        )
        for reference_chain, mobile_counts in sorted(correspondences.items())
    }


def align_structures(
    reference: ProteinStructure,
    mobile: ProteinStructure,
) -> StructureAlignment:
    """Build reproducible sequence correspondence and CA superposition evidence."""
    reference_residues = _parse_pdb_ca(reference.pdb_string)
    mobile_residues = _parse_pdb_ca(mobile.pdb_string)

    if not reference_residues:
        raise ValueError("No CA atoms found in reference structure")
    if not mobile_residues:
        raise ValueError("No CA atoms found in mobile structure")

    reference_sequence = "".join(
        residue.amino_acid for residue in reference_residues
    )
    mobile_sequence = "".join(residue.amino_acid for residue in mobile_residues)
    all_reference_coordinates = np.asarray(
        [residue.coordinate for residue in reference_residues],
        dtype=np.float64,
    )
    all_mobile_coordinates = np.asarray(
        [residue.coordinate for residue in mobile_residues],
        dtype=np.float64,
    )
    reference_indices, mobile_indices = _sequence_correspondence(
        reference_sequence,
        mobile_sequence,
        all_reference_coordinates,
        all_mobile_coordinates,
    )
    if not reference_indices:
        return _record_alignment_evidence(StructureAlignment(
            rotation=[
                [1.0, 0.0, 0.0],
                [0.0, 1.0, 0.0],
                [0.0, 0.0, 1.0],
            ],
            translation=[0.0, 0.0, 0.0],
            reference_sequence=reference_sequence,
            mobile_sequence=mobile_sequence,
            reference_length=len(reference_residues),
            mobile_length=len(mobile_residues),
        ))

    reference_coordinates = np.asarray(
        [
            reference_residues[index].coordinate
            for index in reference_indices
        ],
        dtype=np.float64,
    )
    mobile_coordinates = np.asarray(
        [mobile_residues[index].coordinate for index in mobile_indices],
        dtype=np.float64,
    )

    superimposer = _superimpose(reference_coordinates, mobile_coordinates)
    rotation_array, translation_array = superimposer.get_rotran()
    assert rotation_array is not None
    assert translation_array is not None
    transformed_mobile = np.dot(mobile_coordinates, rotation_array) + translation_array
    distances = np.linalg.norm(
        reference_coordinates - transformed_mobile,
        axis=1,
    )

    return _record_alignment_evidence(StructureAlignment(
        residue_map=[
            (
                reference_residues[reference_index].pdb_label,
                mobile_residues[mobile_index].pdb_label,
            )
            for reference_index, mobile_index in zip(
                reference_indices,
                mobile_indices,
            )
        ],
        chain_map=_chain_map(
            reference_residues,
            mobile_residues,
            reference_indices,
            mobile_indices,
        ),
        rotation=rotation_array.tolist(),
        translation=translation_array.tolist(),
        rmsd=float(superimposer.get_rms()),
        coverage=(
            len(reference_indices)
            / max(len(reference_residues), len(mobile_residues))
        ),
        reference_sequence=reference_sequence,
        mobile_sequence=mobile_sequence,
        reference_length=len(reference_residues),
        mobile_length=len(mobile_residues),
        aligned_reference_indices=reference_indices,
        aligned_mobile_indices=mobile_indices,
        aligned_reference_coordinates=reference_coordinates.tolist(),
        aligned_mobile_coordinates=mobile_coordinates.tolist(),
        aligned_distances=distances.tolist(),
    ))
