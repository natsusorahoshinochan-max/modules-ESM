"""Admit Produced Observations against compiler-resolved typed plans."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
import math
import struct
from typing import Any, Protocol, cast

import rfc8785

from core.scoring.observation_plan import (
    CalibrationContextProfile,
    IntrinsicContextProfile,
    ObservationContextProfile,
    ObservationPropagationFilter,
    ObservationPropagationPlan,
    PairwiseContextProfile,
    ProducedObservationPlan,
    ResolvedMetricFacts,
)
from datatypes.candidate import CandidateDataReference
from datatypes.exact_reference import (
    ExactContractReference,
    ResidueAxisReference,
)
from datatypes.observation import (
    CalibrationObservationContext,
    IntrinsicObservationContext,
    PairwiseObservationContext,
    PairwiseCandidateMapping,
    ScoreCollection,
    ScoreObservation,
)
from datatypes.i_json import thaw_i_json


class ObservationAdmissionError(ValueError):
    """Produced Observation output contradicts its compiler-resolved plan."""


class _AdmittedValue(Protocol):
    value: Any
    content_digest: str


class ObservationAdmissionPort(Protocol):
    """Structural view of one Port already admitted by Output Admission."""

    value: Any
    values: tuple[_AdmittedValue, ...]
    value_content_digests: tuple[str, ...]
    candidate_data: tuple[CandidateDataReference, ...]
    scientific_axes: tuple[ResidueAxisReference, ...]
    observation_methods: tuple[ExactContractReference, ...]


@dataclass(frozen=True, slots=True)
class StructureAlignmentEvidenceAdmissionFacts:
    """Exact facts projected from one admitted alignment-evidence value."""

    subject: CandidateDataReference
    reference: CandidateDataReference
    evidence_content_digest: str
    subject_axis_content_digest: str
    reference_axis_content_digest: str
    evidence_method: ExactContractReference
    reference_axis_residue_count: int
    aligned_atom_count: int


def _canonical_observation_value(value: Any) -> bytes:
    """Project one admitted I-JSON value for exact propagation comparison."""
    return rfc8785.dumps(thaw_i_json(value))


def _validate_resolved_metric_value(
    metric: ResolvedMetricFacts,
    value: object,
    *,
    residue_axis: ResidueAxisReference | None = None,
) -> None:
    if metric.requires_residue_axis:
        if residue_axis is None:
            raise ObservationAdmissionError(
                "Metric requires an exact scientific residue axis"
            )
    elif residue_axis is not None:
        raise ObservationAdmissionError(
            "Metric does not declare a scientific residue-axis population"
        )

    if metric.value_shape == "scalar":
        values = (value,)
    elif metric.value_shape in {"per_residue", "residue_vector"}:
        if not isinstance(value, (list, tuple)):
            raise ObservationAdmissionError(
                "Per-residue Metric value must be an ordered array"
            )
        values = tuple(value)
        if residue_axis is None or len(values) != residue_axis.layout.length:
            raise ObservationAdmissionError(
                "Per-residue Metric value does not align with its exact "
                "residue layout"
            )
    elif metric.value_shape == "residue_pair_matrix":
        if not isinstance(value, (list, tuple)):
            raise ObservationAdmissionError(
                "Residue-pair Metric value must be an ordered matrix"
            )
        residue_count = (
            residue_axis.layout.length if residue_axis is not None else None
        )
        if residue_count is None or len(value) != residue_count:
            raise ObservationAdmissionError(
                "Residue-pair Metric value does not align with its exact "
                "subject residue layout"
            )
        rows = tuple(value)
        if any(
            not isinstance(row, (list, tuple))
            or len(row) != residue_count
            for row in rows
        ):
            raise ObservationAdmissionError(
                "Residue-pair Metric value must be a square residue matrix"
            )
        values = tuple(item for row in rows for item in row)
    else:
        raise ObservationAdmissionError(
            "Selection does not support Metric value shape "
            f"{metric.value_shape!r}"
        )
    for item in values:
        if item is None and metric.allow_null:
            continue
        if (
            isinstance(item, bool)
            or not isinstance(item, (int, float))
            or (metric.require_finite and not math.isfinite(item))
        ):
            raise ObservationAdmissionError(
                "Metric value does not satisfy its validity/masking contract"
            )
        if item < metric.minimum or item > metric.maximum:
            raise ObservationAdmissionError(
                "Metric value is outside its canonical range"
            )
        if metric.exact_binary32:
            try:
                round_trip = struct.unpack(
                    "!f",
                    struct.pack("!f", float(item)),
                )[0]
            except OverflowError as error:
                raise ObservationAdmissionError(
                    "Metric value is not exactly representable as binary32"
                ) from error
            if (
                round_trip != item
                or (
                    item == 0
                    and math.copysign(1.0, round_trip)
                    != math.copysign(1.0, item)
                )
            ):
                raise ObservationAdmissionError(
                    "Metric value is not exactly representable as binary32"
                )


def _deduplicated_observations(
    collection: ScoreCollection,
) -> tuple[ScoreObservation, ...]:
    """Use the first entry after the nominal codec admitted duplicates."""
    observations: dict[tuple[object, ...], ScoreObservation] = {}
    for entry in collection.entries:
        observations.setdefault(entry.identity, entry)
    return tuple(observations.values())


def _context_profile(context: object) -> ObservationContextProfile:
    if isinstance(context, IntrinsicObservationContext):
        return IntrinsicContextProfile()
    if isinstance(context, CalibrationObservationContext):
        return CalibrationContextProfile(
            calibration_metric=context.calibration_metric,
            calibration_value=context.calibration_value,
            calibration_unit=context.calibration_unit,
            population_id=context.population_id,
        )
    if isinstance(context, PairwiseObservationContext):
        return PairwiseContextProfile(
            subject_role=context.subject.role,
            reference_role=context.reference.role,
            pairing_mode=context.pairing_mode,
            normalization=context.normalization,
        )
    raise ObservationAdmissionError("Observation uses an unknown Context type")


def _observation_value_map(
    collection: ScoreCollection,
) -> dict[tuple[object, ...], bytes]:
    return {
        (observation.source_partition, *observation.identity): (
            _canonical_observation_value(observation.value)
        )
        for observation in _deduplicated_observations(collection)
    }


def _observation_matches_propagation_filter(
    observation: ScoreObservation,
    filters: ObservationPropagationFilter,
) -> bool:
    return (
        (
            filters.source_partition is None
            or observation.source_partition
            == filters.source_partition
        )
        and (
            filters.metric is None
            or observation.metric == filters.metric
        )
        and (
            filters.method is None
            or observation.method == filters.method
        )
        and (
            filters.context_profile is None
            or _context_profile(observation.context)
            == filters.context_profile
        )
    )


def _validate_propagated_score_collection(
    *,
    propagation: ObservationPropagationPlan,
    output_port: str,
    collection: ScoreCollection,
    inputs: Mapping[str, ObservationAdmissionPort],
) -> bool:
    if propagation.output_port != output_port:
        return False
    mode = propagation.mode
    source_maps: list[dict[tuple[object, ...], bytes]] = []
    source_observations: list[ScoreObservation] = []
    for input_port in propagation.input_ports:
        source_record = inputs.get(input_port)
        if (
            source_record is None
            and propagation.absent_input_policy == "ignore"
        ):
            continue
        if source_record is None:
            raise ObservationAdmissionError(
                "Binding Observation propagation input is unavailable"
            )
        source = cast(ScoreCollection, source_record.value)
        source_maps.append(_observation_value_map(source))
        source_observations.extend(_deduplicated_observations(source))
    if not source_maps:
        raise ObservationAdmissionError(
            "Binding Observation propagation has no connected input"
        )
    expected: dict[tuple[object, ...], bytes] = {}
    for source_map in source_maps:
        for identity, value in source_map.items():
            existing = expected.get(identity)
            if existing is not None and existing != value:
                raise ObservationAdmissionError(
                    "Observation propagation sources conflict"
                )
            expected[identity] = value
    observed = _observation_value_map(collection)
    if mode in {"pass_through", "union"}:
        if observed != expected:
            raise ObservationAdmissionError(
                "Observation propagation cannot omit, invent, or repartition "
                "entries"
            )
        return True
    filters = propagation.filter
    if filters is None:
        raise ObservationAdmissionError("Filter propagation requires an exact filter")
    filtered_entries = [
        observation
        for observation in source_observations
        if _observation_matches_propagation_filter(
            observation,
            filters,
        )
    ]
    filtered_expected = _observation_value_map(
        ScoreCollection(
            collection_id="controlled-filter-expected",
            entries=filtered_entries,
        )
    )
    if observed != filtered_expected:
        raise ObservationAdmissionError(
            "Observation propagation output is not the exact filter result"
        )
    return True


def _structure_alignment_evidence_facts(
    admitted: ObservationAdmissionPort,
) -> tuple[StructureAlignmentEvidenceAdmissionFacts, ...]:
    """Project cross-value facts from already-admitted alignment evidence."""
    projected: list[StructureAlignmentEvidenceAdmissionFacts] = []
    for admitted_value in admitted.values:
        value = cast(Any, admitted_value.value)
        normalization = value.normalization
        projected.append(
            StructureAlignmentEvidenceAdmissionFacts(
                subject=value.subject,
                reference=value.reference,
                evidence_content_digest=admitted_value.content_digest,
                subject_axis_content_digest=value.subject_axis_content_digest,
                reference_axis_content_digest=value.reference_axis_content_digest,
                evidence_method=value.method,
                reference_axis_residue_count=(
                    normalization.reference_axis_residue_count
                ),
                aligned_atom_count=normalization.aligned_atom_count,
            )
        )
    return tuple(projected)


def _validate_structure_alignment_evidence_provenance(
    *,
    metric: ResolvedMetricFacts,
    observations: Sequence[ScoreObservation],
    evidence: tuple[StructureAlignmentEvidenceAdmissionFacts, ...],
) -> None:
    contract = metric.structure_alignment_evidence
    if contract is None:
        return
    if len(evidence) != len(observations):
        raise ObservationAdmissionError(
            "Produced Observation alignment evidence provenance is incomplete"
        )
    by_pair = {
        (entry.subject, entry.reference): entry for entry in evidence
    }
    if len(by_pair) != len(evidence):
        raise ObservationAdmissionError(
            "Produced Observation alignment evidence provenance is ambiguous"
        )
    observed_pairs: set[
        tuple[CandidateDataReference, CandidateDataReference]
    ] = set()
    normalization_source = contract.normalization_length_source
    for observation in observations:
        context = observation.context
        if type(context) is not PairwiseObservationContext:
            raise ObservationAdmissionError(
                "Produced Observation alignment evidence provenance requires "
                "a pairwise Context"
            )
        pair = (context.subject.candidate, context.reference.candidate)
        admitted = by_pair.get(pair)
        if admitted is None or pair in observed_pairs:
            raise ObservationAdmissionError(
                "Produced Observation alignment evidence provenance does not "
                "resolve exactly once"
            )
        observed_pairs.add(pair)
        expected_normalization_length = (
            admitted.aligned_atom_count
            if normalization_source == "aligned_atom_count"
            else admitted.reference_axis_residue_count
        )
        if (
            context.evidence_content_digest
            != admitted.evidence_content_digest
            or context.evidence_method != admitted.evidence_method
            or context.subject_axis_content_digest
            != admitted.subject_axis_content_digest
            or context.reference_axis_content_digest
            != admitted.reference_axis_content_digest
            or context.normalization_length
            != expected_normalization_length
            or context.aligned_atom_count != admitted.aligned_atom_count
        ):
            raise ObservationAdmissionError(
                "Produced Observation alignment evidence provenance "
                "contradicts its admitted alignment"
            )
    if observed_pairs != set(by_pair):
        raise ObservationAdmissionError(
            "Produced Observation alignment evidence provenance is not closed"
        )


def _directional_source_record(
    *,
    inputs: Mapping[str, ObservationAdmissionPort],
    outputs: Mapping[str, ObservationAdmissionPort],
    direction: str | None,
    port_name: str | None,
) -> ObservationAdmissionPort | None:
    if port_name is None:
        return None
    return inputs.get(port_name) if direction == "input" else outputs.get(port_name)


def admit_produced_observations(
    *,
    plan: ProducedObservationPlan,
    output_port: str,
    collection: ScoreCollection,
    inputs: Mapping[str, ObservationAdmissionPort],
    outputs: Mapping[str, ObservationAdmissionPort],
) -> None:
    """Admit one Score Collection against compiler-resolved exact facts."""
    declarations = plan.observations_for_output(output_port)
    if not declarations:
        if plan.propagation is not None and _validate_propagated_score_collection(
            propagation=plan.propagation,
            output_port=output_port,
            collection=collection,
            inputs=inputs,
        ):
            return
        if any(isinstance(item, ScoreObservation) for item in collection.entries):
            raise ObservationAdmissionError(
                "Binding emitted an undeclared typed Score Observation"
            )
        return

    observations = _deduplicated_observations(collection)
    for observation in observations:
        matches = [
            declaration
            for declaration in declarations
            if declaration.metric == observation.metric
            and declaration.context_profile
            == _context_profile(observation.context)
            and declaration.output_partition == observation.source_partition
            and declaration.subject_grain == "candidate"
            and declaration.source_role == "subject"
        ]
        if len(matches) != 1:
            raise ObservationAdmissionError(
                "Binding emitted an Observation outside its closed Produced "
                "Observation Interface"
            )
        declaration = matches[0]
        if declaration.method_port is None:
            allowed_methods = (plan.binding_method,)
        else:
            method_record = _directional_source_record(
                inputs=inputs,
                outputs=outputs,
                direction=declaration.method_direction,
                port_name=declaration.method_port,
            )
            allowed_methods = (
                method_record.observation_methods
                if method_record is not None
                else ()
            )
        if observation.method not in allowed_methods:
            raise ObservationAdmissionError(
                "Binding emitted an Observation with an undeclared Method"
            )

    for declaration in declarations:
        subject_record = _directional_source_record(
            inputs=inputs,
            outputs=outputs,
            direction=declaration.subject_direction,
            port_name=declaration.subject_port,
        )
        if subject_record is None:
            raise ObservationAdmissionError(
                "Binding Produced Observation Candidate source is unavailable"
            )
        admitted_subjects = subject_record.candidate_data
        subject_ids = tuple(item.candidate_id for item in admitted_subjects)
        if len(subject_ids) != len(set(subject_ids)):
            raise ObservationAdmissionError(
                "Binding Produced Observation subject source has duplicates"
            )
        exact_subjects = {
            item.candidate_id: item for item in admitted_subjects
        }
        matching_observations = [
            observation
            for observation in observations
            if observation.metric == declaration.metric
            and _context_profile(observation.context)
            == declaration.context_profile
            and observation.source_partition == declaration.output_partition
        ]
        resolved_metric = plan.metric_facts[declaration.metric]
        evidence_contract = resolved_metric.structure_alignment_evidence
        evidence: tuple[StructureAlignmentEvidenceAdmissionFacts, ...] = ()
        if evidence_contract is not None:
            evidence_record = _directional_source_record(
                inputs=inputs,
                outputs=outputs,
                direction=evidence_contract.source_direction,
                port_name=evidence_contract.source_port,
            )
            if evidence_record is not None:
                evidence = _structure_alignment_evidence_facts(evidence_record)
        _validate_structure_alignment_evidence_provenance(
            metric=resolved_metric,
            observations=matching_observations,
            evidence=evidence,
        )

        if resolved_metric.requires_residue_axis:
            axis_record = _directional_source_record(
                inputs=inputs,
                outputs=outputs,
                direction=declaration.axis_direction,
                port_name=declaration.axis_port,
            )
            projected_axes = (
                axis_record.scientific_axes if axis_record is not None else ()
            )
            if not projected_axes:
                raise ObservationAdmissionError(
                    "Declared scientific axis Port projected no exact axes"
                )
            for observation in matching_observations:
                axis = observation.residue_axis
                if axis is None or sum(
                    candidate_axis == axis for candidate_axis in projected_axes
                ) != 1:
                    raise ObservationAdmissionError(
                        "Observation residue axis does not resolve exactly once "
                        "from its declared scientific axis Port"
                    )

        mismatched_subjects = [
            observation.candidate_id
            for observation in matching_observations
            if observation.subject
            != exact_subjects.get(observation.candidate_id)
        ]
        if mismatched_subjects:
            raise ObservationAdmissionError(
                "Binding emitted an Observation whose exact subject does not "
                "match its declared Candidate source"
            )
        ghost_subjects = {
            observation.candidate_id
            for observation in matching_observations
        } - set(subject_ids)
        if ghost_subjects:
            raise ObservationAdmissionError(
                "Binding emitted an Observation outside its declared subject "
                "source"
            )

        declared_context = declaration.context_profile
        if isinstance(declared_context, PairwiseContextProfile):
            reference_identities = {
                observation.context.reference.candidate
                for observation in matching_observations
                if isinstance(
                    observation.context,
                    PairwiseObservationContext,
                )
            }
            pairing_mode = declared_context.pairing_mode
            if (
                pairing_mode == "fixed_reference"
                and matching_observations
                and len(reference_identities) != 1
            ):
                raise ObservationAdmissionError(
                    "fixed-reference pairing requires one exact reference "
                    "Candidate for the whole partition"
                )
            if (
                pairing_mode == "per_subject_counterpart"
                and matching_observations
                and len(reference_identities) != len(matching_observations)
            ):
                raise ObservationAdmissionError(
                    "per-subject pairing requires one distinct exact "
                    "counterpart per subject"
                )

        for candidate_id in subject_ids:
            expected_subject = exact_subjects[candidate_id]
            matches = [
                observation
                for observation in matching_observations
                if observation.subject == expected_subject
            ]
            if (
                declaration.guaranteed_multiplicity == "one"
                and len(matches) != 1
            ):
                raise ObservationAdmissionError(
                    "Binding violated guaranteed one Observation per subject"
                )
            if (
                declaration.guaranteed_multiplicity == "one_or_more"
                and not matches
            ):
                raise ObservationAdmissionError(
                    "Binding violated guaranteed one-or-more Observations"
                )
            for observation in matches:
                metric = plan.metric_facts[observation.metric]
                _validate_resolved_metric_value(
                    metric,
                    observation.value,
                    residue_axis=observation.residue_axis,
                )
                if not isinstance(
                    observation.context,
                    PairwiseObservationContext,
                ):
                    continue
                context = observation.context
                if context.subject.candidate != expected_subject:
                    raise ObservationAdmissionError(
                        "Pairwise Context subject source does not match the "
                        "exact Candidate"
                    )
                reference_record = _directional_source_record(
                    inputs=inputs,
                    outputs=outputs,
                    direction=declaration.reference_direction,
                    port_name=declaration.reference_port,
                )
                admitted_references = (
                    reference_record.candidate_data
                    if reference_record is not None
                    else ()
                )
                reference_matches = [
                    reference
                    for reference in admitted_references
                    if reference == context.reference.candidate
                ]
                if len(reference_matches) != 1:
                    raise ObservationAdmissionError(
                        "Pairwise Context reference source does not contain one "
                        "exact Candidate counterpart"
                    )
                if context.pairing_mode != "per_subject_counterpart":
                    continue
                pairing_record = _directional_source_record(
                    inputs=inputs,
                    outputs=outputs,
                    direction=declaration.pairing_direction,
                    port_name=declaration.pairing_port,
                )
                if pairing_record is None:
                    raise ObservationAdmissionError(
                        "Pairwise Candidate pairing source is unavailable"
                    )
                pairing = cast(PairwiseCandidateMapping, pairing_record.value)
                mapping_matches = [
                    entry
                    for entry in pairing.entries
                    if (
                        entry.subject == context.subject.candidate
                        and entry.reference == context.reference.candidate
                    )
                ]
                if len(mapping_matches) != 1:
                    raise ObservationAdmissionError(
                        "Pairwise Context does not match one exact entry in its "
                        "declared pairing source"
                    )
