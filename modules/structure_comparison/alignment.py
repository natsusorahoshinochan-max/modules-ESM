"""Sequence-aware CA alignment owned by structure comparison."""

from collections.abc import Callable
from contextlib import AbstractContextManager, nullcontext
from dataclasses import dataclass
from functools import lru_cache
from importlib.metadata import version
import math

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
        if not line.startswith("ATOM  "):
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


def count_structure_ca_residues(structure: ProteinStructure) -> int:
    """Count residues using the exact CA parsing contract used by alignment."""
    return len(_parse_pdb_ca(structure.pdb_string))


def _sequence_aligner() -> PairwiseAligner:
    aligner = PairwiseAligner(mode="global")
    aligner.substitution_matrix = substitution_matrices.load("BLOSUM62")
    aligner.open_gap_score = _SEQUENCE_GAP_OPEN_SCORE
    aligner.extend_gap_score = _SEQUENCE_GAP_EXTEND_SCORE
    aligner.end_open_gap_score = _SEQUENCE_END_GAP_OPEN_SCORE
    aligner.end_extend_gap_score = _SEQUENCE_END_GAP_EXTEND_SCORE
    return aligner


def _sequence_correspondence(
    reference_sequence: str,
    mobile_sequence: str,
    reference_coordinates: np.ndarray,
    mobile_coordinates: np.ndarray,
    *,
    engine_invocation: (
        Callable[..., AbstractContextManager[str]] | None
    ),
) -> tuple[list[int], list[int], str | None]:
    """Return sequence-optimal pairs with structure-aware tie resolution."""
    sequence_context = (
        engine_invocation(
            engine_role="sequence_alignment",
            engine_identity=(
                "Bio.Align.PairwiseAligner/"
                f"{version('biopython')}"
            ),
        )
        if engine_invocation is not None
        else nullcontext(None)
    )
    with sequence_context as sequence_invocation_id:
        aligner = _sequence_aligner()
        sequence_alignments = aligner.align(
            reference_sequence,
            mobile_sequence,
        )

        try:
            alignment_count = len(sequence_alignments)
        except OverflowError:
            alignment_count = _MAX_EXHAUSTIVE_SEQUENCE_ALIGNMENTS + 1

    selection_context = (
        engine_invocation(
            engine_role="bounded_correspondence_selection",
            engine_identity=(
                "structure_alignment.bounded_correspondence_selection/"
                f"Bio.SVDSuperimposer-{version('biopython')}/"
                f"numpy-{version('numpy')}"
            ),
            parent_invocation_id=sequence_invocation_id,
        )
        if engine_invocation is not None
        else nullcontext(None)
    )
    with selection_context:
        best_correspondence: tuple[list[int], list[int]] | None = None
        best_key: tuple[int, float, tuple[int, ...], tuple[int, ...]] | None = None
        alignment_limit = (
            1
            if alignment_count > _MAX_EXHAUSTIVE_SEQUENCE_ALIGNMENTS
            else alignment_count
        )
        for alignment_index, alignment in enumerate(sequence_alignments):
            if alignment_index >= alignment_limit:
                break
            paired_indices = [
                (int(reference_index), int(mobile_index))
                for reference_index, mobile_index in zip(*alignment.indices)
                if reference_index >= 0 and mobile_index >= 0
            ]
            reference_indices = [
                reference_index for reference_index, _ in paired_indices
            ]
            mobile_indices = [
                mobile_index for _, mobile_index in paired_indices
            ]
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
                best_correspondence = (
                    reference_indices,
                    mobile_indices,
                )

    if best_correspondence is None:
        return [], [], sequence_invocation_id
    return (*best_correspondence, sequence_invocation_id)


def _residues_by_chain(
    residues: list[_ResidueCA],
) -> dict[str, tuple[int, ...]]:
    chains: dict[str, list[int]] = {}
    for index, residue in enumerate(residues):
        chains.setdefault(residue.chain, []).append(index)
    return {
        chain: tuple(indices)
        for chain, indices in chains.items()
    }


def _sequence_score(
    residues: list[_ResidueCA],
    indices: tuple[int, ...],
    other_residues: list[_ResidueCA],
    other_indices: tuple[int, ...],
) -> float:
    sequence = "".join(residues[index].amino_acid for index in indices)
    other_sequence = "".join(
        other_residues[index].amino_acid for index in other_indices
    )
    return float(_sequence_aligner().score(sequence, other_sequence))


def _sequence_optimal_chain_maps(
    reference_residues: list[_ResidueCA],
    mobile_residues: list[_ResidueCA],
) -> tuple[list[dict[str, str]], bool]:
    """Return bounded, lexicographic sequence-optimal one-to-one chain maps."""
    reference_chains = _residues_by_chain(reference_residues)
    mobile_chains = _residues_by_chain(mobile_residues)
    common = sorted(set(reference_chains) & set(mobile_chains))
    fixed = {chain: chain for chain in common}
    remaining_reference = sorted(set(reference_chains) - set(common))
    remaining_mobile = sorted(set(mobile_chains) - set(common))
    if not remaining_reference or not remaining_mobile:
        return [fixed], False

    inverse = len(remaining_reference) > len(remaining_mobile)
    left = remaining_mobile if inverse else remaining_reference
    right = remaining_reference if inverse else remaining_mobile

    def pair_score(left_chain: str, right_chain: str) -> float:
        reference_chain = right_chain if inverse else left_chain
        mobile_chain = left_chain if inverse else right_chain
        return _sequence_score(
            reference_residues,
            reference_chains[reference_chain],
            mobile_residues,
            mobile_chains[mobile_chain],
        )

    scores = tuple(
        tuple(pair_score(left_chain, right_chain) for right_chain in right)
        for left_chain in left
    )

    @lru_cache(maxsize=None)
    def best_score(left_index: int, used_mask: int) -> float:
        if left_index == len(left):
            return 0.0
        return max(
            scores[left_index][right_index]
            + best_score(left_index + 1, used_mask | (1 << right_index))
            for right_index in range(len(right))
            if not used_mask & (1 << right_index)
        )

    assignments: list[tuple[int, ...]] = []

    def collect(
        left_index: int,
        used_mask: int,
        selected: tuple[int, ...],
    ) -> None:
        if len(assignments) > _MAX_EXHAUSTIVE_SEQUENCE_ALIGNMENTS:
            return
        if left_index == len(left):
            assignments.append(selected)
            return
        optimum = best_score(left_index, used_mask)
        for right_index in range(len(right)):
            if used_mask & (1 << right_index):
                continue
            branch_score = (
                scores[left_index][right_index]
                + best_score(
                    left_index + 1,
                    used_mask | (1 << right_index),
                )
            )
            if math.isclose(
                branch_score,
                optimum,
                rel_tol=0.0,
                abs_tol=1e-12,
            ):
                collect(
                    left_index + 1,
                    used_mask | (1 << right_index),
                    (*selected, right_index),
                )

    collect(0, 0, ())
    exceeded = len(assignments) > _MAX_EXHAUSTIVE_SEQUENCE_ALIGNMENTS
    maps: list[dict[str, str]] = []
    for assignment in assignments[: _MAX_EXHAUSTIVE_SEQUENCE_ALIGNMENTS + 1]:
        chain_map = dict(fixed)
        for left_index, right_index in enumerate(assignment):
            if inverse:
                chain_map[right[right_index]] = left[left_index]
            else:
                chain_map[left[left_index]] = right[right_index]
        maps.append(dict(sorted(chain_map.items())))
    maps.sort(key=lambda mapping: tuple(mapping.items()))
    return maps, exceeded


def _correspondence_for_chain_map(
    chain_map: dict[str, str],
    reference_residues: list[_ResidueCA],
    mobile_residues: list[_ResidueCA],
    reference_coordinates: np.ndarray,
    mobile_coordinates: np.ndarray,
    *,
    engine_invocation: (
        Callable[..., AbstractContextManager[str]] | None
    ),
) -> tuple[list[int], list[int], str | None]:
    reference_chains = _residues_by_chain(reference_residues)
    mobile_chains = _residues_by_chain(mobile_residues)
    pairs: list[tuple[int, int]] = []
    parent_invocation_id: str | None = None
    for reference_chain, mobile_chain in sorted(chain_map.items()):
        reference_global = reference_chains[reference_chain]
        mobile_global = mobile_chains[mobile_chain]
        reference_sequence = "".join(
            reference_residues[index].amino_acid
            for index in reference_global
        )
        mobile_sequence = "".join(
            mobile_residues[index].amino_acid for index in mobile_global
        )
        local_reference_coordinates = reference_coordinates[
            list(reference_global)
        ]
        local_mobile_coordinates = mobile_coordinates[list(mobile_global)]
        (
            local_reference_indices,
            local_mobile_indices,
            invocation_id,
        ) = _sequence_correspondence(
            reference_sequence,
            mobile_sequence,
            local_reference_coordinates,
            local_mobile_coordinates,
            engine_invocation=engine_invocation,
        )
        if parent_invocation_id is None:
            parent_invocation_id = invocation_id
        pairs.extend(
            (
                reference_global[reference_index],
                mobile_global[mobile_index],
            )
            for reference_index, mobile_index in zip(
                local_reference_indices,
                local_mobile_indices,
            )
        )
    pairs.sort()
    return (
        [reference_index for reference_index, _ in pairs],
        [mobile_index for _, mobile_index in pairs],
        parent_invocation_id,
    )


def align_structures(
    reference: ProteinStructure,
    mobile: ProteinStructure,
    *,
    engine_invocation: (
        Callable[..., AbstractContextManager[str]] | None
    ) = None,
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
    chain_maps, chain_map_limit_exceeded = _sequence_optimal_chain_maps(
        reference_residues,
        mobile_residues,
    )
    if chain_map_limit_exceeded:
        selected_chain_map = chain_maps[0]
    else:
        selected_chain_map: dict[str, str] | None = None
        selected_key: tuple[float, tuple[tuple[str, str], ...]] | None = None
        for chain_map in chain_maps:
            trial_reference_indices, trial_mobile_indices, _ = (
                _correspondence_for_chain_map(
                    chain_map,
                    reference_residues,
                    mobile_residues,
                    all_reference_coordinates,
                    all_mobile_coordinates,
                    engine_invocation=None,
                )
            )
            if trial_reference_indices:
                trial_rmsd = float(
                    _superimpose(
                        all_reference_coordinates[trial_reference_indices],
                        all_mobile_coordinates[trial_mobile_indices],
                    ).get_rms()
                )
            else:
                trial_rmsd = float("inf")
            key = (trial_rmsd, tuple(sorted(chain_map.items())))
            if selected_key is None or key < selected_key:
                selected_key = key
                selected_chain_map = chain_map
        assert selected_chain_map is not None
    (
        reference_indices,
        mobile_indices,
        sequence_invocation_id,
    ) = _correspondence_for_chain_map(
        selected_chain_map,
        reference_residues,
        mobile_residues,
        all_reference_coordinates,
        all_mobile_coordinates,
        engine_invocation=engine_invocation,
    )
    if not reference_indices:
        return StructureAlignment(
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
        )

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

    superposition_context = (
        engine_invocation(
            engine_role="rigid_superposition",
            engine_identity=(
                "Bio.SVDSuperimposer/"
                f"{version('biopython')}/"
                f"numpy-{version('numpy')}"
            ),
            parent_invocation_id=sequence_invocation_id,
        )
        if engine_invocation is not None
        else nullcontext(None)
    )
    with superposition_context:
        superimposer = _superimpose(
            reference_coordinates,
            mobile_coordinates,
        )
        rotation_array, translation_array = superimposer.get_rotran()
        fit_rmsd = float(superimposer.get_rms())
    assert rotation_array is not None
    assert translation_array is not None
    transformed_mobile = (
        np.dot(mobile_coordinates, rotation_array) + translation_array
    )
    distances = np.linalg.norm(
        reference_coordinates - transformed_mobile,
        axis=1,
    )
    return StructureAlignment(
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
        chain_map=selected_chain_map,
        rotation=rotation_array.tolist(),
        translation=translation_array.tolist(),
        rmsd=fit_rmsd,
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
    )
