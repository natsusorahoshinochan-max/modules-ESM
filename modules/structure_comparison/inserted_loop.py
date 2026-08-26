"""Exact inserted-loop evidence evaluation over admitted scientific values."""

from __future__ import annotations

import math
from typing import Any, Protocol, cast

from core.operation import (
    AdmittedPort,
    OperationCall,
)
from datatypes.candidate import (
    Candidate,
    CandidateCollection,
    CandidateDataReference,
)
from datatypes.exact_reference import (
    ExactContractReference,
    ResidueAxisReference,
)
from datatypes.observation import (
    IntrinsicObservationContext,
    PairwiseCandidateMapping,
    PairwiseObservationContext,
    ScoreCollection,
    ScoreObservation,
)
from datatypes.structure import ResolvedStructureResidueAxis
from .contracts import (
    ESMFOLD2_FOLD_METHOD_REFERENCES,
    INSERTED_LOOP_EVALUATION_METHOD_REFERENCE,
    RMSD_FROM_EVIDENCE_METHOD_REFERENCE,
    TM_SCORE_FROM_EVIDENCE_METHOD_REFERENCE,
)
from .domain import (
    AtomPairDistanceEvidence,
    InsertedLoopCandidateEvidence,
    InsertedLoopEvaluationCollection,
    InsertedLoopThresholds,
    ResidueIdentityCorrespondence,
    StructureAlignmentEvidence,
)


class _ResolvedAxisAssociation(Protocol):
    """Structural view of one admitted resolved-axis association."""

    subject: CandidateDataReference
    residue_axis: ResolvedStructureResidueAxis


class _ResolvedAxisAssociations(Protocol):
    """Structural view of the resolved-axis capability collection."""

    entries: tuple[_ResolvedAxisAssociation, ...]


def _candidate_scope(
    call: OperationCall,
    port: str,
) -> tuple[
    CandidateCollection,
    dict[str, CandidateDataReference],
]:
    admitted = call.inputs[port]
    collection = cast(CandidateCollection, admitted.value)
    if collection.item_type != "protein.structure" or not collection.items:
        raise ValueError(f"{port} must be exact structure Candidates")
    references = {
        reference.candidate_id: reference for reference in admitted.candidate_data
    }
    return collection, references


def _axes_by_subject(
    admitted: AdmittedPort,
    references: dict[str, CandidateDataReference],
) -> dict[
    CandidateDataReference,
    tuple[ResolvedStructureResidueAxis, ResidueAxisReference],
]:
    associations = cast(
        _ResolvedAxisAssociations,
        admitted.value,
    )
    axes = {entry.subject: entry.residue_axis for entry in associations.entries}
    if set(axes) != set(references.values()):
        raise ValueError("subject residue axes do not cover exact subjects")
    admitted_axes = {axis.source: axis for axis in admitted.scientific_axes}
    return {
        subject: (axis, admitted_axes[subject])
        for subject, axis in axes.items()
    }


def _alignment_values(
    call: OperationCall,
    port: str,
) -> dict[CandidateDataReference, tuple[StructureAlignmentEvidence, str]]:
    admitted = call.inputs[port]
    values = cast(tuple[StructureAlignmentEvidence, ...], admitted.value)
    if not values or len(admitted.value_content_digests) != len(values):
        raise ValueError(f"{port} must contain exact alignment evidence")
    result = {
        value.subject: (value, digest)
        for value, digest in zip(
            values,
            admitted.value_content_digests,
            strict=True,
        )
    }
    if len(result) != len(values):
        raise ValueError(f"{port} repeats one exact subject")
    return result


def _score_by_subject(
    value: object,
    *,
    metric_id: str,
    method: ExactContractReference,
) -> dict[CandidateDataReference, ScoreObservation]:
    collection = cast(ScoreCollection, value)
    selected = tuple(
        observation
        for observation in collection.entries
        if observation.metric.contract_id == metric_id
        and observation.metric.contract_version == "3.0.0"
        and observation.method == method
    )
    result = {observation.subject: observation for observation in selected}
    if len(result) != len(selected):
        raise ValueError(f"{metric_id} scores repeat one exact subject")
    return result


def _paired_counterparts(
    value: object,
    subjects: dict[str, CandidateDataReference],
    counterparts: dict[str, CandidateDataReference],
) -> dict[CandidateDataReference, CandidateDataReference]:
    pairing = cast(PairwiseCandidateMapping, value)
    result = {entry.subject: entry.reference for entry in pairing.entries}
    if set(result) != set(subjects.values()) or set(result.values()) != set(
        counterparts.values()
    ):
        raise ValueError("counterpart pairing is not a complete exact mapping")
    return result


def _score_value(
    scores: dict[CandidateDataReference, ScoreObservation],
    subject: CandidateDataReference,
    alignment: StructureAlignmentEvidence,
    alignment_digest: str,
) -> float:
    observation = scores.get(subject)
    if (
        observation is None
        or type(observation.context) is not PairwiseObservationContext
        or observation.context.subject.candidate != subject
        or observation.context.reference.candidate != alignment.reference
        or observation.context.evidence_content_digest != alignment_digest
        or observation.context.evidence_method != alignment.method
        or observation.context.normalization_length
        != alignment.normalization.reference_axis_residue_count
        or observation.context.aligned_atom_count
        != alignment.normalization.aligned_atom_count
    ):
        raise ValueError("pairwise score contradicts exact alignment evidence")
    return float(observation.value)


def _per_residue_confidence(
    value: object,
) -> dict[CandidateDataReference, ScoreObservation]:
    collection = cast(ScoreCollection, value)
    selected = tuple(
        observation
        for observation in collection.entries
        if observation.metric.contract_id == "structure.plddt.per_residue"
        and observation.metric.contract_version == "3.0.0"
        and observation.method in ESMFOLD2_FOLD_METHOD_REFERENCES
        and type(observation.context) is IntrinsicObservationContext
        and observation.source_partition == "prediction_confidence"
    )
    result = {observation.subject: observation for observation in selected}
    if len(result) != len(selected):
        raise ValueError("confidence repeats one exact per-residue subject")
    return result


def _mean_scope(
    values: tuple[object, ...],
    index_by_id: dict[str, int],
    residue_ids: tuple[str, ...],
) -> float:
    scoped = tuple(values[index_by_id[residue_id]] for residue_id in residue_ids)
    if any(
        isinstance(value, bool) or not isinstance(value, (int, float))
        for value in scoped
    ):
        raise ValueError("required residue-scoped pLDDT evidence is missing")
    return math.fsum(float(value) for value in scoped) / len(scoped)


def _atom_pair(
    *,
    left_prediction_id: str,
    left_structure_id: str,
    left_atom_name: str,
    left_coordinate: tuple[float, float, float],
    right_prediction_id: str,
    right_structure_id: str,
    right_atom_name: str,
    right_coordinate: tuple[float, float, float],
) -> AtomPairDistanceEvidence:
    return AtomPairDistanceEvidence(
        left_prediction_residue_id=left_prediction_id,
        left_structure_residue_id=left_structure_id,
        left_atom_name=left_atom_name,
        left_coordinate=left_coordinate,
        right_prediction_residue_id=right_prediction_id,
        right_structure_residue_id=right_structure_id,
        right_atom_name=right_atom_name,
        right_coordinate=right_coordinate,
        distance_angstrom=math.dist(left_coordinate, right_coordinate),
    )


def _is_hydrogen(atom_name: str) -> bool:
    element = atom_name.lstrip("0123456789")
    return bool(element) and element.startswith("H")


class EvaluateInsertedLoopImplementation:
    """Close exact reference, counterpart, confidence, and geometry evidence."""

    def execute(self, call: OperationCall) -> dict[str, Any]:
        subjects, subject_references = _candidate_scope(call, "subjects")
        references, reference_references = _candidate_scope(call, "references")
        counterparts, counterpart_references = _candidate_scope(
            call,
            "counterparts",
        )
        if len(references.items) != 1:
            raise ValueError("inserted-loop evaluation requires one fixed reference")
        reference = next(iter(reference_references.values()))
        axes = _axes_by_subject(
            call.inputs["subject_residue_axes"],
            subject_references,
        )
        paired = _paired_counterparts(
            call.inputs["counterpart_pairing"].value,
            subject_references,
            counterpart_references,
        )
        core_alignments = _alignment_values(
            call,
            "resolved_core_alignments",
        )
        counterpart_alignments = _alignment_values(
            call,
            "counterpart_alignments",
        )
        core_tm = _score_by_subject(
            call.inputs["resolved_core_tm_scores"].value,
            metric_id="structure_comparison.tm_score",
            method=TM_SCORE_FROM_EVIDENCE_METHOD_REFERENCE,
        )
        core_rmsd = _score_by_subject(
            call.inputs["resolved_core_rmsd_scores"].value,
            metric_id="structure_comparison.rmsd",
            method=RMSD_FROM_EVIDENCE_METHOD_REFERENCE,
        )
        counterpart_tm = _score_by_subject(
            call.inputs["counterpart_tm_scores"].value,
            metric_id="structure_comparison.tm_score",
            method=TM_SCORE_FROM_EVIDENCE_METHOD_REFERENCE,
        )
        counterpart_rmsd = _score_by_subject(
            call.inputs["counterpart_rmsd_scores"].value,
            metric_id="structure_comparison.rmsd",
            method=RMSD_FROM_EVIDENCE_METHOD_REFERENCE,
        )
        confidence = _per_residue_confidence(
            call.inputs["confidence_observations"].value
        )
        expected_subjects = set(subject_references.values())
        for mapping in (
            core_alignments,
            counterpart_alignments,
            core_tm,
            core_rmsd,
            counterpart_tm,
            counterpart_rmsd,
            confidence,
        ):
            if set(mapping) != expected_subjects:
                raise ValueError("inserted-loop evidence does not cover subjects")

        parameters = call.node_parameters
        core_ids = tuple(parameters["resolved_core_residue_ids"])
        loop_ids = tuple(parameters["loop_residue_ids"])
        left_id = parameters["left_junction_residue_id"]
        right_id = parameters["right_junction_residue_id"]
        if (
            not core_ids
            or not loop_ids
            or len(set(core_ids)) != len(core_ids)
            or len(set(loop_ids)) != len(loop_ids)
            or set(core_ids) & set(loop_ids)
            or left_id not in core_ids
            or right_id not in core_ids
        ):
            raise ValueError("inserted-loop residue scopes are invalid")
        thresholds = InsertedLoopThresholds(
            resolved_core_tm_score_minimum=float(
                parameters["resolved_core_tm_score_minimum"]
            ),
            resolved_core_rmsd_angstrom_maximum=float(
                parameters["resolved_core_rmsd_angstrom_maximum"]
            ),
            counterpart_tm_score_minimum=float(
                parameters["counterpart_tm_score_minimum"]
            ),
            counterpart_rmsd_angstrom_maximum=float(
                parameters["counterpart_rmsd_angstrom_maximum"]
            ),
            resolved_core_mean_plddt_minimum=float(
                parameters["resolved_core_mean_plddt_minimum"]
            ),
            junction_cn_distance_angstrom_minimum=float(
                parameters["junction_cn_distance_angstrom_minimum"]
            ),
            junction_cn_distance_angstrom_maximum=float(
                parameters["junction_cn_distance_angstrom_maximum"]
            ),
            loop_core_nonbonded_distance_angstrom_minimum=float(
                parameters["loop_core_nonbonded_distance_angstrom_minimum"]
            ),
        )
        confidence_digests = call.inputs[
            "confidence_observations"
        ].value_content_digests
        if len(confidence_digests) != 1:
            raise ValueError("confidence observations require one exact collection")
        confidence_digest = confidence_digests[0]

        entries: list[InsertedLoopCandidateEvidence] = []
        passing: list[Candidate] = []
        for candidate in subjects.items:
            subject = subject_references[candidate.candidate_id]
            subject_axis, subject_axis_reference = axes[subject]
            confidence_observation = confidence[subject]
            prediction_axis = confidence_observation.residue_axis
            values = confidence_observation.value
            if (
                prediction_axis is None
                or len(values) != prediction_axis.layout.length
                or prediction_axis.layout.length != subject_axis.layout.length
            ):
                raise ValueError(
                    "prediction confidence and output structure axes do not align"
                )
            prediction_ids = tuple(prediction_axis.layout.residue_ids or ())
            structure_ids = tuple(subject_axis.layout.residue_ids or ())
            if len(prediction_ids) != len(structure_ids) or set(prediction_ids) != set(
                core_ids
            ) | set(loop_ids):
                raise ValueError(
                    "prediction axis does not equal the declared core plus loop"
                )
            prediction_index = {
                residue_id: index for index, residue_id in enumerate(prediction_ids)
            }
            if (
                tuple(
                    prediction_ids[
                        prediction_index[left_id] + 1 : prediction_index[right_id]
                    ]
                )
                != loop_ids
            ):
                raise ValueError("inserted-loop scope is not between its junctions")
            structure_by_prediction = dict(
                zip(prediction_ids, structure_ids, strict=True)
            )
            correspondence = tuple(
                ResidueIdentityCorrespondence(prediction_id, structure_id)
                for prediction_id, structure_id in zip(
                    prediction_ids,
                    structure_ids,
                    strict=True,
                )
            )

            core_alignment, core_alignment_digest = core_alignments[subject]
            counterpart_alignment, counterpart_alignment_digest = (
                counterpart_alignments[subject]
            )
            counterpart = paired[subject]
            if (
                core_alignment.reference != reference
                or tuple(
                    item.reference_residue_id for item in core_alignment.correspondence
                )
                != core_ids
                or core_alignment.normalization.reference_axis_residue_count
                != len(core_ids)
                or core_alignment.normalization.aligned_atom_count != len(core_ids)
                or counterpart_alignment.reference != counterpart
                or counterpart_alignment.normalization.aligned_atom_count
                != len(prediction_ids)
            ):
                raise ValueError(
                    "alignment evidence does not close exact core/counterpart scope"
                )
            core_tm_value = _score_value(
                core_tm,
                subject,
                core_alignment,
                core_alignment_digest,
            )
            core_rmsd_value = _score_value(
                core_rmsd,
                subject,
                core_alignment,
                core_alignment_digest,
            )
            counterpart_tm_value = _score_value(
                counterpart_tm,
                subject,
                counterpart_alignment,
                counterpart_alignment_digest,
            )
            counterpart_rmsd_value = _score_value(
                counterpart_rmsd,
                subject,
                counterpart_alignment,
                counterpart_alignment_digest,
            )
            core_plddt = _mean_scope(values, prediction_index, core_ids)
            loop_plddt = _mean_scope(values, prediction_index, loop_ids)

            left_structure_id = structure_by_prediction[left_id]
            first_loop_structure_id = structure_by_prediction[loop_ids[0]]
            last_loop_structure_id = structure_by_prediction[loop_ids[-1]]
            right_structure_id = structure_by_prediction[right_id]
            left_junction = _atom_pair(
                left_prediction_id=left_id,
                left_structure_id=left_structure_id,
                left_atom_name="C",
                left_coordinate=subject_axis.coordinate_for(
                    left_structure_id,
                    "C",
                ),
                right_prediction_id=loop_ids[0],
                right_structure_id=first_loop_structure_id,
                right_atom_name="N",
                right_coordinate=subject_axis.coordinate_for(
                    first_loop_structure_id,
                    "N",
                ),
            )
            right_junction = _atom_pair(
                left_prediction_id=loop_ids[-1],
                left_structure_id=last_loop_structure_id,
                left_atom_name="C",
                left_coordinate=subject_axis.coordinate_for(
                    last_loop_structure_id,
                    "C",
                ),
                right_prediction_id=right_id,
                right_structure_id=right_structure_id,
                right_atom_name="N",
                right_coordinate=subject_axis.coordinate_for(
                    right_structure_id,
                    "N",
                ),
            )

            excluded = {
                (loop_ids[0], "N", left_id, "C"),
                (loop_ids[-1], "C", right_id, "N"),
            }
            atom_pairs: list[AtomPairDistanceEvidence] = []
            for loop_id in loop_ids:
                loop_structure_id = structure_by_prediction[loop_id]
                for loop_atom in subject_axis.coordinates_for(loop_structure_id):
                    if _is_hydrogen(loop_atom.atom_name):
                        continue
                    for core_id in core_ids:
                        core_structure_id = structure_by_prediction[core_id]
                        for core_atom in subject_axis.coordinates_for(
                            core_structure_id
                        ):
                            if (
                                _is_hydrogen(core_atom.atom_name)
                                or (
                                    loop_id,
                                    loop_atom.atom_name,
                                    core_id,
                                    core_atom.atom_name,
                                )
                                in excluded
                            ):
                                continue
                            atom_pairs.append(
                                _atom_pair(
                                    left_prediction_id=loop_id,
                                    left_structure_id=loop_structure_id,
                                    left_atom_name=loop_atom.atom_name,
                                    left_coordinate=loop_atom.coordinate,
                                    right_prediction_id=core_id,
                                    right_structure_id=core_structure_id,
                                    right_atom_name=core_atom.atom_name,
                                    right_coordinate=core_atom.coordinate,
                                )
                            )
            minimum_distance = min(
                atom_pairs,
                key=lambda item: (
                    item.distance_angstrom,
                    item.left_prediction_residue_id,
                    item.left_atom_name,
                    item.right_prediction_residue_id,
                    item.right_atom_name,
                ),
            )
            gate_results = (
                core_tm_value >= thresholds.resolved_core_tm_score_minimum
                and core_rmsd_value <= thresholds.resolved_core_rmsd_angstrom_maximum,
                counterpart_tm_value >= thresholds.counterpart_tm_score_minimum
                and counterpart_rmsd_value
                <= thresholds.counterpart_rmsd_angstrom_maximum,
                core_plddt >= thresholds.resolved_core_mean_plddt_minimum,
                all(
                    thresholds.junction_cn_distance_angstrom_minimum
                    <= item.distance_angstrom
                    <= thresholds.junction_cn_distance_angstrom_maximum
                    for item in (left_junction, right_junction)
                ),
                minimum_distance.distance_angstrom
                >= thresholds.loop_core_nonbonded_distance_angstrom_minimum,
            )
            accepted = all(gate_results)
            entries.append(
                InsertedLoopCandidateEvidence(
                    subject=subject,
                    reference=reference,
                    counterpart=counterpart,
                    prediction_axis_content_digest=(
                        prediction_axis.axis_content_digest
                    ),
                    structure_axis_content_digest=(
                        subject_axis_reference.axis_content_digest
                    ),
                    prediction_to_structure_correspondence=correspondence,
                    resolved_core_residue_ids=core_ids,
                    loop_residue_ids=loop_ids,
                    resolved_core_alignment_content_digest=core_alignment_digest,
                    counterpart_alignment_content_digest=counterpart_alignment_digest,
                    resolved_core_tm_score=core_tm_value,
                    resolved_core_rmsd_angstrom=core_rmsd_value,
                    counterpart_tm_score=counterpart_tm_value,
                    counterpart_rmsd_angstrom=counterpart_rmsd_value,
                    confidence_collection_content_digest=confidence_digest,
                    confidence_method=confidence_observation.method,
                    resolved_core_mean_plddt=core_plddt,
                    loop_mean_plddt=loop_plddt,
                    left_junction=left_junction,
                    right_junction=right_junction,
                    minimum_loop_core_nonbonded_distance=minimum_distance,
                    thresholds=thresholds,
                    resolved_core_passed=gate_results[0],
                    counterpart_passed=gate_results[1],
                    confidence_passed=gate_results[2],
                    junctions_passed=gate_results[3],
                    clash_passed=gate_results[4],
                    accepted=accepted,
                    method=INSERTED_LOOP_EVALUATION_METHOD_REFERENCE,
                )
            )
            if accepted:
                passing.append(candidate)

        return {
            "quality_evidence": InsertedLoopEvaluationCollection(tuple(entries)),
            "passing_candidates": CandidateCollection(
                collection_id="inserted-loop-passing-candidates",
                item_type="protein.structure",
                items=tuple(passing),
            ),
        }


__all__ = ["EvaluateInsertedLoopImplementation"]
