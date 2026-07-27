"""Standard TM-score calculation from shared StructureAlignment evidence."""

from dataclasses import dataclass
from importlib.metadata import version
from math import isfinite

import numpy as np
from tmtools import tm_align

from datatypes import Score, StructureAlignment


@dataclass(frozen=True)
class ReferenceNormalizedTMScore:
    value: float
    normalization_length: int
    aligned_residues: int
    reference_coverage: float
    d0: float


def _fixed_correspondence_alignment(
    reference_length: int,
    mobile_length: int,
    reference_indices: list[int],
    mobile_indices: list[int],
) -> tuple[str, str]:
    reference_alignment: list[str] = []
    mobile_alignment: list[str] = []
    reference_cursor = 0
    mobile_cursor = 0

    for reference_index, mobile_index in zip(
        reference_indices,
        mobile_indices,
    ):
        while reference_cursor < reference_index:
            reference_alignment.append("A")
            mobile_alignment.append("-")
            reference_cursor += 1
        while mobile_cursor < mobile_index:
            reference_alignment.append("-")
            mobile_alignment.append("A")
            mobile_cursor += 1
        reference_alignment.append("A")
        mobile_alignment.append("A")
        reference_cursor += 1
        mobile_cursor += 1

    while reference_cursor < reference_length:
        reference_alignment.append("A")
        mobile_alignment.append("-")
        reference_cursor += 1
    while mobile_cursor < mobile_length:
        reference_alignment.append("-")
        mobile_alignment.append("A")
        mobile_cursor += 1

    return "".join(reference_alignment), "".join(mobile_alignment)


def calculate_reference_normalized_tm_score(
    alignment: StructureAlignment,
) -> ReferenceNormalizedTMScore:
    """Calculate standard TM-score terms normalized by reference length."""
    normalization_length = alignment.reference_length
    if normalization_length <= 0:
        raise ValueError("Alignment reference_length must be positive")
    if alignment.mobile_length <= 0:
        raise ValueError("Alignment mobile_length must be positive")

    aligned_residues = len(alignment.residue_map)
    evidence_lengths = {
        len(alignment.aligned_reference_indices),
        len(alignment.aligned_mobile_indices),
        len(alignment.aligned_reference_coordinates),
        len(alignment.aligned_mobile_coordinates),
        len(alignment.aligned_distances),
    }
    if evidence_lengths != {aligned_residues}:
        raise ValueError(
            "Alignment correspondence, coordinates, and distances must have "
            "equal length"
        )
    if aligned_residues > normalization_length:
        raise ValueError(
            "Alignment cannot contain more aligned residues than reference_length"
        )
    if aligned_residues > alignment.mobile_length:
        raise ValueError(
            "Alignment cannot contain more aligned residues than mobile_length"
        )
    if any(
        not isfinite(distance) or distance < 0.0
        for distance in alignment.aligned_distances
    ):
        raise ValueError("Alignment distances must be finite and non-negative")
    if alignment.aligned_reference_indices != sorted(
        set(alignment.aligned_reference_indices)
    ) or any(
        index < 0 or index >= normalization_length
        for index in alignment.aligned_reference_indices
    ):
        raise ValueError("Alignment reference indices must be unique and ordered")
    if alignment.aligned_mobile_indices != sorted(
        set(alignment.aligned_mobile_indices)
    ) or any(
        index < 0 or index >= alignment.mobile_length
        for index in alignment.aligned_mobile_indices
    ):
        raise ValueError("Alignment mobile indices must be unique and ordered")

    reference_coordinates = np.asarray(
        alignment.aligned_reference_coordinates,
        dtype=np.float64,
    )
    mobile_coordinates = np.asarray(
        alignment.aligned_mobile_coordinates,
        dtype=np.float64,
    )
    if aligned_residues and (
        reference_coordinates.shape != (aligned_residues, 3)
        or mobile_coordinates.shape != (aligned_residues, 3)
    ):
        raise ValueError("Alignment coordinates must be finite three-vectors")
    if aligned_residues and (
        not np.isfinite(reference_coordinates).all()
        or not np.isfinite(mobile_coordinates).all()
    ):
        raise ValueError("Alignment coordinates must be finite three-vectors")

    if normalization_length > 15:
        d0 = 1.24 * (normalization_length - 15) ** (1.0 / 3.0) - 1.8
    else:
        d0 = 0.5
    d0 = max(d0, 0.5)

    value = 0.0
    if aligned_residues:
        full_reference_coordinates = np.zeros(
            (normalization_length, 3),
            dtype=np.float64,
        )
        full_mobile_coordinates = np.zeros(
            (alignment.mobile_length, 3),
            dtype=np.float64,
        )
        full_reference_coordinates[
            alignment.aligned_reference_indices
        ] = reference_coordinates
        full_mobile_coordinates[
            alignment.aligned_mobile_indices
        ] = mobile_coordinates
        fixed_alignment = _fixed_correspondence_alignment(
            normalization_length,
            alignment.mobile_length,
            alignment.aligned_reference_indices,
            alignment.aligned_mobile_indices,
        )
        optimized = tm_align(
            full_reference_coordinates,
            full_mobile_coordinates,
            "A" * normalization_length,
            "A" * alignment.mobile_length,
            fixed_alignment,
        )
        transformed_mobile = (
            mobile_coordinates @ np.asarray(optimized.u, dtype=np.float64).T
            + np.asarray(optimized.t, dtype=np.float64)
        )
        optimized_distances = np.linalg.norm(
            reference_coordinates - transformed_mobile,
            axis=1,
        )
        value = float(
            np.sum(1.0 / (1.0 + (optimized_distances / d0) ** 2))
            / normalization_length
        )

    result = ReferenceNormalizedTMScore(
        value=value,
        normalization_length=normalization_length,
        aligned_residues=aligned_residues,
        reference_coverage=aligned_residues / normalization_length,
        d0=d0,
    )
    if aligned_residues:
        from core.provider_evidence import record_provider_call_result

        record_provider_call_result(
            provider="tmtools",
            operation="tm_score",
            model="tm_align-fixed-correspondence",
            provider_identity={"tmtools_version": version("tmtools")},
            effective_seed=None,
            seed_control="deterministic_no_rng",
            result_summary={
                "value": result.value,
                "normalization": "reference",
                "normalization_length": result.normalization_length,
                "aligned_residues": result.aligned_residues,
                "reference_coverage": result.reference_coverage,
                "d0": result.d0,
            },
        )
    return result


def score_reference_normalized_alignment(
    alignment: StructureAlignment,
    *,
    score_id: str,
    subjects: list[str],
) -> Score:
    """Create a Score with explicit reference-normalization semantics."""
    tm_score = calculate_reference_normalized_tm_score(alignment)
    return Score(
        score_id=score_id,
        value=round(tm_score.value, 4),
        subjects=subjects,
        details={
            "rmsd": round(float(alignment.rmsd), 4),
            "aligned_residues": tm_score.aligned_residues,
            "coverage": round(tm_score.reference_coverage, 4),
            "d0": round(tm_score.d0, 4),
            "normalization": "reference",
            "normalization_length": tm_score.normalization_length,
        },
    )
