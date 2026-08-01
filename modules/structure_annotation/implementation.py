"""Canonical Scientific Operations for the structure-annotation package."""

from __future__ import annotations

from typing import Any, Mapping, Protocol

from core import OperationCall, ResolvedProducedObservation, RunResources
from datatypes import (
    CandidateCollection,
    ExactContractReference,
    PairwiseObservationContext,
    PairwiseParticipant,
    ProteinStructure,
    ScoreCollection,
    ScoreObservation,
)

from .domain import DSSPAnnotation, StructureAnnotationTrack


class _DSSPAdapter(Protocol):
    """Canonical-only internal seam used by the DSSP Operation."""

    def annotate(self, structure: ProteinStructure) -> DSSPAnnotation: ...


def _reject_parameters(call: OperationCall) -> None:
    if call.node_parameters or call.binding_parameters:
        raise ValueError("structure annotation Nodes do not accept parameters")


def _annotation_input(inputs: Mapping[str, Any]) -> DSSPAnnotation:
    if set(inputs) != {"annotations"}:
        raise ValueError(
            "annotation extraction requires exactly one annotation input"
        )
    annotation = inputs["annotations"]
    if type(annotation) is not DSSPAnnotation:
        raise ValueError("annotations must be a DSSPAnnotation")
    return annotation


class DSSPComputeOperation:
    """Expose mkdssp annotation through canonical scientific values only."""

    def __init__(self, adapter: _DSSPAdapter) -> None:
        self._adapter = adapter

    def execute(self, call: OperationCall) -> dict[str, Any]:
        _reject_parameters(call)
        if set(call.inputs) != {"structure"}:
            raise ValueError(
                "DSSP computation requires exactly one structure input"
            )
        structure = call.inputs["structure"]
        if type(structure) is not ProteinStructure:
            raise ValueError("DSSP computation requires one ProteinStructure")
        annotation = self._adapter.annotate(structure)
        if type(annotation) is not DSSPAnnotation:
            raise RuntimeError("mkdssp Adapter returned a non-canonical value")
        return {"annotations": annotation}


class SecondaryStructureExtractOperation:
    """Extract the canonical SS8 track without crossing a provider seam."""

    def __init__(self, resources: RunResources) -> None:
        self._resources = resources

    def execute(self, call: OperationCall) -> dict[str, Any]:
        _reject_parameters(call)
        annotation = _annotation_input(call.inputs)
        with self._resources.engine_invocation():
            track = StructureAnnotationTrack(
                layout=annotation.layout,
                values=tuple(
                    "C" if value == "P" else value
                    for value in annotation.secondary_structure
                ),
            )
        return {"secondary_structure_track": track}


class SASAComputeOperation:
    """Extract canonical DSSP accessibility without a provider Adapter."""

    def __init__(self, resources: RunResources) -> None:
        self._resources = resources

    def execute(self, call: OperationCall) -> dict[str, Any]:
        _reject_parameters(call)
        annotation = _annotation_input(call.inputs)
        with self._resources.engine_invocation():
            track = StructureAnnotationTrack(
                layout=annotation.layout,
                values=annotation.sasa,
            )
        return {"sasa_track": track}


class SecondaryStructureAgreementOperation:
    """Compute one exact SS8 agreement Observation directly."""

    def __init__(
        self,
        *,
        resources: RunResources,
        method: ExactContractReference,
        produced_observations: tuple[ResolvedProducedObservation, ...],
    ) -> None:
        self._resources = resources
        self._method = method
        self._produced_observations = produced_observations

    def _produced_observation(self) -> ResolvedProducedObservation:
        matches = tuple(
            observation
            for observation in self._produced_observations
            if observation.output_port == "scores"
        )
        if len(matches) != 1:
            raise RuntimeError(
                "agreement Binding must resolve one exact Observation"
            )
        return matches[0]

    @staticmethod
    def _candidate_digest(
        call: OperationCall,
        *,
        port_name: str,
        candidate_id: str,
    ) -> str:
        digest_record = call.input_content_digests[port_name]
        matches = tuple(
            candidate.content_digest
            for candidate in digest_record.candidate_data
            if candidate.candidate_id == candidate_id
        )
        if len(matches) != 1:
            raise ValueError(
                f"{port_name} lacks one exact Candidate content identity"
            )
        return matches[0]

    def execute(self, call: OperationCall) -> dict[str, Any]:
        _reject_parameters(call)
        inputs = call.inputs
        if set(inputs) != {
            "subjects",
            "references",
            "expected",
            "observed",
        }:
            raise ValueError(
                "secondary-structure agreement requires subjects, references, "
                "expected, and observed"
            )
        subjects = inputs["subjects"]
        references = inputs["references"]
        expected = inputs["expected"]
        observed = inputs["observed"]
        if (
            type(subjects) is not CandidateCollection
            or len(subjects.items) != 1
            or not subjects.items[0].candidate_id
        ):
            raise ValueError(
                "secondary-structure agreement requires exactly one "
                "identified Candidate"
            )
        if (
            type(references) is not CandidateCollection
            or len(references.items) != 1
            or not references.items[0].candidate_id
        ):
            raise ValueError(
                "secondary-structure agreement requires exactly one "
                "identified reference Candidate"
            )
        if (
            type(expected) is not StructureAnnotationTrack
            or type(observed) is not StructureAnnotationTrack
        ):
            raise ValueError(
                "agreement inputs must be exact structure-annotation tracks"
            )
        if expected.layout != observed.layout:
            raise ValueError(
                "agreement tracks must carry one identical exact layout"
            )
        if (
            len(expected.values) != expected.layout.length
            or len(observed.values) != observed.layout.length
        ):
            raise ValueError("agreement track length contradicts its layout")
        with self._resources.engine_invocation():
            compared = [
                (expected_value, observed_value)
                for expected_value, observed_value in zip(
                    expected.values,
                    observed.values,
                    strict=True,
                )
                if expected_value != "_" and observed_value != "_"
            ]
            if not compared:
                raise ValueError(
                    "agreement requires at least one present residue pair"
                )
            agreement = sum(
                expected_value == observed_value
                for expected_value, observed_value in compared
            ) / len(compared)
            subject = subjects.items[0]
            reference = references.items[0]
            subject_digest = self._candidate_digest(
                call,
                port_name="subjects",
                candidate_id=subject.candidate_id,
            )
            reference_digest = self._candidate_digest(
                call,
                port_name="references",
                candidate_id=reference.candidate_id,
            )
            produced = self._produced_observation()
            profile = produced.context_profile
            observation = ScoreObservation(
                candidate_id=subject.candidate_id,
                metric=produced.metric,
                method=self._method,
                context=PairwiseObservationContext(
                    subject=PairwiseParticipant(
                        role="subject",
                        candidate_id=subject.candidate_id,
                        content_digest=subject_digest,
                    ),
                    reference=PairwiseParticipant(
                        role="reference",
                        candidate_id=reference.candidate_id,
                        content_digest=reference_digest,
                    ),
                    pairing_mode=str(profile["pairing_mode"]),
                    normalization=str(profile["normalization"]),
                ),
                value=agreement,
                source_partition=produced.output_partition,
            )
        return {
            "scores": ScoreCollection(
                collection_id="structure-annotation-agreement",
                entries=[observation],
            )
        }
