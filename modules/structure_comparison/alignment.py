"""Sequence-aware CA alignment owned by structure comparison."""

from dataclasses import dataclass
from typing import cast

import numpy as np
from Bio.Align import substitution_matrices
from Bio.SVDSuperimposer import SVDSuperimposer
from scipy.optimize import linear_sum_assignment
from tmtools import tm_align

from datatypes import ResolvedStructureResidueAxis

from .domain import (
    AlignmentAtomCorrespondence,
    AlignmentCorrespondencePolicy,
    AlignmentSegmentMapEntry,
    ResolvedAxisAlignment,
    StructureAlignmentNormalization,
    StructureAlignmentTransform,
)


_BLOSUM62 = substitution_matrices.load("BLOSUM62")
_SCALED_GAP_OPEN = -6
_SCALED_GAP_EXTEND = -1
_SCALED_TERMINAL_GAP_OPEN = -4
_SCALED_TERMINAL_GAP_EXTEND = -1
_NEGATIVE_OBJECTIVE = (-10**18, -1)


@dataclass(frozen=True, slots=True)
class _AffineAlignment:
    score: int
    paired_count: int
    cigar: str
    reference_indices: tuple[int, ...]
    subject_indices: tuple[int, ...]


def _superimpose(
    reference_coordinates: np.ndarray,
    mobile_coordinates: np.ndarray,
) -> SVDSuperimposer:
    superimposer = SVDSuperimposer()
    superimposer.set(reference_coordinates, mobile_coordinates)
    superimposer.run()
    return superimposer


def _substitution_score(reference: str, subject: str) -> int:
    try:
        return int(round(float(_BLOSUM62[reference, subject]) * 2.0))
    except (IndexError, KeyError) as error:
        raise ValueError(
            "resolved-axis sequence is outside the BLOSUM62 alphabet"
        ) from error


def _affine_sequence_alignment(
    reference: str,
    subject: str,
) -> _AffineAlignment:
    """Solve exact affine global alignment with an iterative suffix table."""

    match_state, deletion_state, insertion_state = range(3)
    reference_length = len(reference)
    subject_length = len(subject)
    negative_score = _NEGATIVE_OBJECTIVE[0]
    scores = np.full(
        (3, reference_length + 1, subject_length + 1),
        negative_score,
        dtype=np.int64,
    )
    paired_counts = np.full(
        (3, reference_length + 1, subject_length + 1),
        -1,
        dtype=np.int32,
    )
    scores[:, reference_length, subject_length] = 0
    paired_counts[:, reference_length, subject_length] = 0

    def extend(
        state: int,
        reference_index: int,
        subject_index: int,
        score: int,
        paired_count: int,
    ) -> tuple[int, int]:
        tail_score = int(scores[state, reference_index, subject_index])
        if tail_score == negative_score:
            return _NEGATIVE_OBJECTIVE
        return (
            score + tail_score,
            paired_count
            + int(paired_counts[state, reference_index, subject_index]),
        )

    for reference_index in range(reference_length, -1, -1):
        for subject_index in range(subject_length, -1, -1):
            if (
                reference_index == reference_length
                and subject_index == subject_length
            ):
                continue
            matched = _NEGATIVE_OBJECTIVE
            if (
                reference_index < reference_length
                and subject_index < subject_length
            ):
                matched = extend(
                    match_state,
                    reference_index + 1,
                    subject_index + 1,
                    _substitution_score(
                        reference[reference_index],
                        subject[subject_index],
                    ),
                    1,
                )
            deletion_open = _NEGATIVE_OBJECTIVE
            deletion_extend = _NEGATIVE_OBJECTIVE
            if reference_index < reference_length:
                terminal = subject_index in {0, subject_length}
                deletion_open = extend(
                    deletion_state,
                    reference_index + 1,
                    subject_index,
                    _SCALED_TERMINAL_GAP_OPEN
                    if terminal
                    else _SCALED_GAP_OPEN,
                    0,
                )
                deletion_extend = extend(
                    deletion_state,
                    reference_index + 1,
                    subject_index,
                    _SCALED_TERMINAL_GAP_EXTEND
                    if terminal
                    else _SCALED_GAP_EXTEND,
                    0,
                )
            insertion_open = _NEGATIVE_OBJECTIVE
            insertion_extend = _NEGATIVE_OBJECTIVE
            if subject_index < subject_length:
                terminal = reference_index in {0, reference_length}
                insertion_open = extend(
                    insertion_state,
                    reference_index,
                    subject_index + 1,
                    _SCALED_TERMINAL_GAP_OPEN
                    if terminal
                    else _SCALED_GAP_OPEN,
                    0,
                )
                insertion_extend = extend(
                    insertion_state,
                    reference_index,
                    subject_index + 1,
                    _SCALED_TERMINAL_GAP_EXTEND
                    if terminal
                    else _SCALED_GAP_EXTEND,
                    0,
                )
            objectives = (
                max(matched, deletion_open, insertion_open),
                max(matched, deletion_extend, insertion_open),
                max(matched, deletion_open, insertion_extend),
            )
            for state, objective in enumerate(objectives):
                scores[state, reference_index, subject_index] = objective[0]
                paired_counts[state, reference_index, subject_index] = (
                    objective[1]
                )

    objective = (
        int(scores[match_state, 0, 0]),
        int(paired_counts[match_state, 0, 0]),
    )
    if objective == _NEGATIVE_OBJECTIVE:
        raise ValueError("resolved-axis sequences have no global alignment")
    reference_index = 0
    subject_index = 0
    previous_state = match_state
    cigar: list[str] = []
    reference_indices: list[int] = []
    subject_indices: list[int] = []
    while (
        reference_index != reference_length
        or subject_index != subject_length
    ):
        current = (
            int(scores[previous_state, reference_index, subject_index]),
            int(
                paired_counts[
                    previous_state,
                    reference_index,
                    subject_index,
                ]
            ),
        )
        selected: tuple[str, int, int, int] | None = None
        for operation in ("M", "D", "I"):
            if operation == "M":
                if (
                    reference_index >= reference_length
                    or subject_index >= subject_length
                ):
                    continue
                candidate = extend(
                    match_state,
                    reference_index + 1,
                    subject_index + 1,
                    _substitution_score(
                        reference[reference_index],
                        subject[subject_index],
                    ),
                    1,
                )
                step = (1, 1, match_state)
            elif operation == "D":
                if reference_index >= reference_length:
                    continue
                terminal = subject_index in {0, subject_length}
                candidate = extend(
                    deletion_state,
                    reference_index + 1,
                    subject_index,
                    (
                        _SCALED_TERMINAL_GAP_EXTEND
                        if previous_state == deletion_state and terminal
                        else _SCALED_GAP_EXTEND
                        if previous_state == deletion_state
                        else _SCALED_TERMINAL_GAP_OPEN
                        if terminal
                        else _SCALED_GAP_OPEN
                    ),
                    0,
                )
                step = (1, 0, deletion_state)
            else:
                if subject_index >= subject_length:
                    continue
                terminal = reference_index in {0, reference_length}
                candidate = extend(
                    insertion_state,
                    reference_index,
                    subject_index + 1,
                    (
                        _SCALED_TERMINAL_GAP_EXTEND
                        if previous_state == insertion_state and terminal
                        else _SCALED_GAP_EXTEND
                        if previous_state == insertion_state
                        else _SCALED_TERMINAL_GAP_OPEN
                        if terminal
                        else _SCALED_GAP_OPEN
                    ),
                    0,
                )
                step = (0, 1, insertion_state)
            if candidate != current:
                continue
            selected = (operation, *step)
            break
        if selected is None:
            raise RuntimeError("affine suffix table cannot be backtraced")
        operation, reference_step, subject_step, previous_state = selected
        cigar.append(operation)
        if operation == "M":
            reference_indices.append(reference_index)
            subject_indices.append(subject_index)
        reference_index += reference_step
        subject_index += subject_step
    return _AffineAlignment(
        score=objective[0],
        paired_count=objective[1],
        cigar="".join(cigar),
        reference_indices=tuple(reference_indices),
        subject_indices=tuple(subject_indices),
    )


def _segment_sequence(
    axis: ResolvedStructureResidueAxis,
    segment_index: int,
) -> tuple[str, tuple[str, ...]]:
    segment = axis.segments[segment_index]
    residue_ids = tuple(segment.residue_ids)
    layout_residue_ids = cast(tuple[str, ...], axis.layout.residue_ids)
    sequence_by_id = dict(
        zip(layout_residue_ids, axis.sequence, strict=True)
    )
    return "".join(sequence_by_id[item] for item in residue_ids), residue_ids


def _assignment_score(
    subject_indices: tuple[int, ...],
    reference_indices: tuple[int, ...],
    weights: dict[tuple[int, int], int],
) -> int:
    if not subject_indices or not reference_indices:
        return 0
    matrix = np.asarray(
        [
            [
                weights[(subject_index, reference_index)]
                for reference_index in reference_indices
            ]
            for subject_index in subject_indices
        ],
        dtype=np.int64,
    )
    rows, columns = linear_sum_assignment(matrix, maximize=True)
    return sum(int(matrix[row, column]) for row, column in zip(rows, columns))


def _lexicographic_segment_assignment(
    subject_indices: tuple[int, ...],
    reference_indices: tuple[int, ...],
    alignments: dict[tuple[int, int], _AffineAlignment],
    *,
    maximum_paired_count: int,
) -> tuple[tuple[int, int], ...]:
    """Select one polynomial-time optimum and its exact lexicographic map."""

    score_scale = maximum_paired_count + 1
    weights = {
        pair: alignment.score * score_scale + alignment.paired_count
        for pair, alignment in alignments.items()
    }
    remaining_subjects = subject_indices
    remaining_references = reference_indices
    remaining_optimum = _assignment_score(
        remaining_subjects,
        remaining_references,
        weights,
    )
    selected: list[tuple[int, int]] = []
    for subject_index in subject_indices:
        if subject_index not in remaining_subjects:
            continue
        tail_subjects = tuple(
            item for item in remaining_subjects if item != subject_index
        )
        candidates: tuple[int | None, ...] = (
            *remaining_references,
            *(
                (None,)
                if len(remaining_subjects) > len(remaining_references)
                else ()
            ),
        )
        chosen: int | None | object = ...
        for reference_index in candidates:
            if reference_index is None:
                branch_score = _assignment_score(
                    tail_subjects,
                    remaining_references,
                    weights,
                )
            else:
                tail_references = tuple(
                    item
                    for item in remaining_references
                    if item != reference_index
                )
                branch_score = weights[(subject_index, reference_index)] + (
                    _assignment_score(
                        tail_subjects,
                        tail_references,
                        weights,
                    )
                )
            if branch_score == remaining_optimum:
                chosen = reference_index
                break
        if chosen is ...:
            raise RuntimeError("optimal segment assignment cannot be backtraced")
        remaining_subjects = tail_subjects
        if chosen is not None:
            assert isinstance(chosen, int)
            selected.append((subject_index, chosen))
            remaining_optimum -= weights[(subject_index, chosen)]
            remaining_references = tuple(
                item for item in remaining_references if item != chosen
            )
    return tuple(selected)


def _assign_segments(
    subject_axis: ResolvedStructureResidueAxis,
    reference_axis: ResolvedStructureResidueAxis,
    alignments: dict[tuple[int, int], _AffineAlignment],
    *,
    pin_matching_chain_ids: bool,
) -> tuple[tuple[int, int], ...]:
    subject_indices = tuple(segment.segment_index for segment in subject_axis.segments)
    reference_indices = tuple(
        segment.segment_index for segment in reference_axis.segments
    )
    pinned: tuple[tuple[int, int], ...] = ()
    if pin_matching_chain_ids:
        subject_by_chain = {
            segment.chain_id: segment.segment_index
            for segment in subject_axis.segments
        }
        reference_by_chain = {
            segment.chain_id: segment.segment_index
            for segment in reference_axis.segments
        }
        if len(subject_by_chain) != len(subject_axis.segments):
            raise ValueError("subject axis has duplicate chain_id under pinning")
        if len(reference_by_chain) != len(reference_axis.segments):
            raise ValueError("reference axis has duplicate chain_id under pinning")
        pinned = tuple(
            (subject_by_chain[chain_id], reference_by_chain[chain_id])
            for chain_id in subject_by_chain
            if chain_id in reference_by_chain
        )
        pinned_subjects = {subject_index for subject_index, _ in pinned}
        pinned_references = {reference_index for _, reference_index in pinned}
        subject_indices = tuple(
            item for item in subject_indices if item not in pinned_subjects
        )
        reference_indices = tuple(
            item for item in reference_indices if item not in pinned_references
        )
    assigned = _lexicographic_segment_assignment(
        subject_indices,
        reference_indices,
        alignments,
        maximum_paired_count=min(
            subject_axis.layout.length,
            reference_axis.layout.length,
        ),
    )
    return tuple(sorted((*pinned, *assigned)))


def _align_resolved_axes_tm_align(
    subject_axis: ResolvedStructureResidueAxis,
    reference_axis: ResolvedStructureResidueAxis,
    *,
    pin_matching_chain_ids: bool,
) -> ResolvedAxisAlignment:
    if len(subject_axis.segments) != 1 or len(reference_axis.segments) != 1:
        raise ValueError("structure-first tm_align requires one segment per axis")
    subject_residue_ids = cast(
        tuple[str, ...], subject_axis.layout.residue_ids
    )
    reference_residue_ids = cast(
        tuple[str, ...], reference_axis.layout.residue_ids
    )
    subject_entries = tuple(
        (residue_id, amino_acid, subject_axis.coordinate_for(residue_id, "CA"))
        for residue_id, amino_acid, has_ca in zip(
            subject_residue_ids,
            subject_axis.sequence,
            subject_axis.ca_coordinate_mask,
            strict=True,
        )
        if has_ca
    )
    reference_entries = tuple(
        (
            residue_id,
            amino_acid,
            reference_axis.coordinate_for(residue_id, "CA"),
        )
        for residue_id, amino_acid, has_ca in zip(
            reference_residue_ids,
            reference_axis.sequence,
            reference_axis.ca_coordinate_mask,
            strict=True,
        )
        if has_ca
    )
    if not subject_entries or not reference_entries:
        raise ValueError("structure-first tm_align requires CA coordinates")
    subject_coordinates = np.asarray(
        [item[2] for item in subject_entries],
        dtype=np.float64,
    )
    reference_coordinates = np.asarray(
        [item[2] for item in reference_entries],
        dtype=np.float64,
    )
    subject_sequence = "".join(item[1] for item in subject_entries)
    reference_sequence = "".join(item[1] for item in reference_entries)
    optimized = tm_align(
        subject_coordinates,
        reference_coordinates,
        subject_sequence,
        reference_sequence,
        alignment=None,
    )
    aligned_subject = optimized.seqxA
    aligned_reference = optimized.seqyA
    subject_index = 0
    reference_index = 0
    cigar: list[str] = []
    residue_pairs: list[tuple[str, str]] = []
    for subject_letter, reference_letter in zip(
        aligned_subject,
        aligned_reference,
    ):
        if subject_letter != "-" and reference_letter != "-":
            cigar.append("M")
            residue_pairs.append(
                (
                    subject_entries[subject_index][0],
                    reference_entries[reference_index][0],
                )
            )
        elif subject_letter == "-":
            cigar.append("D")
        else:
            cigar.append("I")
        subject_index += subject_letter != "-"
        reference_index += reference_letter != "-"
    rotation_array = np.asarray(optimized.u, dtype=np.float64).T
    translation_array = np.asarray(optimized.t, dtype=np.float64)
    paired_subject_coordinates = np.asarray(
        [subject_axis.coordinate_for(item[0], "CA") for item in residue_pairs],
        dtype=np.float64,
    )
    paired_reference_coordinates = np.asarray(
        [reference_axis.coordinate_for(item[1], "CA") for item in residue_pairs],
        dtype=np.float64,
    )
    transformed_subject = (
        paired_subject_coordinates @ rotation_array + translation_array
    )
    distances = np.linalg.norm(
        paired_reference_coordinates - transformed_subject,
        axis=1,
    )
    correspondence = tuple(
        AlignmentAtomCorrespondence(
            subject_residue_id=subject_id,
            subject_atom_name="CA",
            subject_coordinate=tuple(float(item) for item in subject_coordinate),
            reference_residue_id=reference_id,
            reference_atom_name="CA",
            reference_coordinate=tuple(
                float(item) for item in reference_coordinate
            ),
            transformed_subject_coordinate=tuple(
                float(item) for item in transformed_coordinate
            ),
            residual_distance=float(distance),
        )
        for (
            (subject_id, reference_id),
            subject_coordinate,
            reference_coordinate,
            transformed_coordinate,
            distance,
        ) in zip(
            residue_pairs,
            paired_subject_coordinates,
            paired_reference_coordinates,
            transformed_subject,
            distances,
            strict=True,
        )
    )
    aligned_count = len(correspondence)
    return ResolvedAxisAlignment(
        segment_map=(
            AlignmentSegmentMapEntry(
                subject_segment_index=0,
                reference_segment_index=0,
                subject_chain_id=subject_axis.segments[0].chain_id,
                reference_chain_id=reference_axis.segments[0].chain_id,
                sequence_score=None,
                paired_residue_count=aligned_count,
                cigar="".join(cigar),
            ),
        ),
        policy=AlignmentCorrespondencePolicy(
            kind="structure_first_tm_align",
            pin_matching_chain_ids=pin_matching_chain_ids,
        ),
        correspondence=correspondence,
        transform=StructureAlignmentTransform(
            maps_from_role="subject",
            maps_to_role="reference",
            row_vector_rotation=tuple(
                tuple(float(item) for item in row) for row in rotation_array
            ),
            translation=tuple(float(item) for item in translation_array),
        ),
        normalization=StructureAlignmentNormalization(
            subject_axis_residue_count=subject_axis.layout.length,
            reference_axis_residue_count=reference_axis.layout.length,
            subject_ca_count=sum(subject_axis.ca_coordinate_mask),
            reference_ca_count=sum(reference_axis.ca_coordinate_mask),
            aligned_atom_count=aligned_count,
        ),
        rmsd=float(np.sqrt(np.mean(np.square(distances)))),
        coverage=aligned_count
        / max(subject_axis.layout.length, reference_axis.layout.length),
    )


def align_resolved_axes(
    subject_axis: ResolvedStructureResidueAxis,
    reference_axis: ResolvedStructureResidueAxis,
    *,
    correspondence_method: str = "sequence_primary_affine",
    pin_matching_chain_ids: bool = False,
) -> ResolvedAxisAlignment:
    """Align two resolved scalar axes by sequence before one global SVD."""

    if correspondence_method == "structure_first_tm_align":
        return _align_resolved_axes_tm_align(
            subject_axis,
            reference_axis,
            pin_matching_chain_ids=pin_matching_chain_ids,
        )
    if correspondence_method != "sequence_primary_affine":
        raise ValueError("unknown structure correspondence method")
    subject_segments = {
        segment.segment_index: _segment_sequence(
            subject_axis,
            segment.segment_index,
        )
        for segment in subject_axis.segments
    }
    reference_segments = {
        segment.segment_index: _segment_sequence(
            reference_axis,
            segment.segment_index,
        )
        for segment in reference_axis.segments
    }
    sequence_alignments = {
        (subject_index, reference_index): _affine_sequence_alignment(
            reference_segments[reference_index][0],
            subject_segments[subject_index][0],
        )
        for subject_index in subject_segments
        for reference_index in reference_segments
    }
    assigned_segments = _assign_segments(
        subject_axis,
        reference_axis,
        sequence_alignments,
        pin_matching_chain_ids=pin_matching_chain_ids,
    )
    segment_map = tuple(
        AlignmentSegmentMapEntry(
            subject_segment_index=subject_index,
            reference_segment_index=reference_index,
            subject_chain_id=subject_axis.segments[subject_index].chain_id,
            reference_chain_id=(
                reference_axis.segments[reference_index].chain_id
            ),
            sequence_score=sequence_alignments[
                (subject_index, reference_index)
            ].score,
            paired_residue_count=sequence_alignments[
                (subject_index, reference_index)
            ].paired_count,
            cigar=sequence_alignments[(subject_index, reference_index)].cigar,
        )
        for subject_index, reference_index in assigned_segments
    )
    subject_residue_ids = cast(
        tuple[str, ...], subject_axis.layout.residue_ids
    )
    reference_residue_ids = cast(
        tuple[str, ...], reference_axis.layout.residue_ids
    )
    subject_mask = dict(
        zip(
            subject_residue_ids,
            subject_axis.ca_coordinate_mask,
            strict=True,
        )
    )
    reference_mask = dict(
        zip(
            reference_residue_ids,
            reference_axis.ca_coordinate_mask,
            strict=True,
        )
    )
    residue_pairs_list: list[tuple[str, str]] = []
    for subject_segment_index, reference_segment_index in assigned_segments:
        alignment = sequence_alignments[
            (subject_segment_index, reference_segment_index)
        ]
        subject_ids = subject_segments[subject_segment_index][1]
        reference_ids = reference_segments[reference_segment_index][1]
        residue_pairs_list.extend(
            (subject_ids[subject_index], reference_ids[reference_index])
            for reference_index, subject_index in zip(
                alignment.reference_indices,
                alignment.subject_indices,
                strict=True,
            )
            if subject_mask[subject_ids[subject_index]]
            and reference_mask[reference_ids[reference_index]]
        )
    residue_pairs = tuple(residue_pairs_list)
    if not residue_pairs:
        raise ValueError("alignment correspondence contains no paired CA atoms")
    subject_coordinates = np.asarray(
        [subject_axis.coordinate_for(item[0], "CA") for item in residue_pairs],
        dtype=np.float64,
    )
    reference_coordinates = np.asarray(
        [reference_axis.coordinate_for(item[1], "CA") for item in residue_pairs],
        dtype=np.float64,
    )
    superimposer = _superimpose(reference_coordinates, subject_coordinates)
    rotation_array, translation_array = superimposer.get_rotran()
    assert rotation_array is not None
    assert translation_array is not None
    transformed_subject = subject_coordinates @ rotation_array + translation_array
    distances = np.linalg.norm(
        reference_coordinates - transformed_subject,
        axis=1,
    )
    correspondence = tuple(
        AlignmentAtomCorrespondence(
            subject_residue_id=subject_id,
            subject_atom_name="CA",
            subject_coordinate=tuple(float(item) for item in subject_coordinate),
            reference_residue_id=reference_id,
            reference_atom_name="CA",
            reference_coordinate=tuple(
                float(item) for item in reference_coordinate
            ),
            transformed_subject_coordinate=tuple(
                float(item) for item in transformed_coordinate
            ),
            residual_distance=float(distance),
        )
        for (
            (subject_id, reference_id),
            subject_coordinate,
            reference_coordinate,
            transformed_coordinate,
            distance,
        ) in zip(
            residue_pairs,
            subject_coordinates,
            reference_coordinates,
            transformed_subject,
            distances,
            strict=True,
        )
    )
    aligned_count = len(correspondence)
    return ResolvedAxisAlignment(
        segment_map=segment_map,
        policy=AlignmentCorrespondencePolicy(
            kind="sequence_primary_affine",
            pin_matching_chain_ids=pin_matching_chain_ids,
        ),
        correspondence=correspondence,
        transform=StructureAlignmentTransform(
            maps_from_role="subject",
            maps_to_role="reference",
            row_vector_rotation=tuple(
                tuple(float(item) for item in row)
                for row in rotation_array
            ),
            translation=tuple(float(item) for item in translation_array),
        ),
        normalization=StructureAlignmentNormalization(
            subject_axis_residue_count=subject_axis.layout.length,
            reference_axis_residue_count=reference_axis.layout.length,
            subject_ca_count=sum(subject_axis.ca_coordinate_mask),
            reference_ca_count=sum(reference_axis.ca_coordinate_mask),
            aligned_atom_count=aligned_count,
        ),
        rmsd=float(superimposer.get_rms()),
        coverage=aligned_count
        / max(subject_axis.layout.length, reference_axis.layout.length),
    )
