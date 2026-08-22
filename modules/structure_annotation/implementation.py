"""Canonical Scientific Operations for the structure-annotation package."""

from __future__ import annotations

from dataclasses import replace
from typing import Any, Mapping, Protocol, cast

from core.operation import (
    OperationResources,
    AdmittedPort,
    OperationCall,
)
from core.scoring.observation_plan import (
    PairwiseContextProfile,
    ResolvedProducedObservation,
)
from datatypes.candidate import CandidateDataReference
from datatypes.exact_reference import ExactContractReference
from datatypes.observation import (
    PairwiseObservationContext,
    PairwiseParticipant,
    ScoreCollection,
    ScoreObservation,
)
from datatypes.residue import ResidueTrack
from datatypes.structure import ResolvedStructureResidueAxis
from .domain import DSSPAnnotation, StructureAnnotationTrack


_ANNOTATION_TO_PROMPT_SS = {
    "G": "G",
    "H": "H",
    "I": "I",
    "T": "T",
    "E": "E",
    "B": "B",
    "S": "S",
    "C": "-",
    "_": None,
}
_PROMPT_TO_ANNOTATION_SS = {
    "G": "G",
    "H": "H",
    "I": "I",
    "T": "T",
    "E": "E",
    "B": "B",
    "S": "S",
    "-": "C",
    None: "_",
}


class _DSSPAdapter(Protocol):
    """Canonical-only internal seam used by the DSSP Operation."""

    def annotate(
        self,
        residue_axis: ResolvedStructureResidueAxis,
        *,
        subject: CandidateDataReference,
    ) -> DSSPAnnotation: ...


def _annotation_input(inputs: Mapping[str, AdmittedPort]) -> DSSPAnnotation:
    return inputs["annotations"].value


def _singleton_candidate_reference(
    call: OperationCall,
    *,
    port_name: str,
) -> CandidateDataReference:
    collection = call.inputs[port_name].value
    if len(collection.items) != 1:
        raise ValueError(f"{port_name} must contain exactly one Candidate")
    return call.inputs[port_name].candidate_data[0]


class DSSPComputeOperation:
    """Expose mkdssp annotation through canonical scientific values only."""

    def __init__(self, adapter: _DSSPAdapter) -> None:
        self._adapter = adapter

    def execute(self, call: OperationCall) -> dict[str, Any]:
        subject = _singleton_candidate_reference(
            call,
            port_name="structure_candidates",
        )
        associations = call.inputs["residue_axes"].value
        if (
            len(associations.entries) != 1
            or associations.entries[0].subject != subject
        ):
            raise ValueError(
                "residue_axes must contain one exact resolved residue-axis "
                "association for the admitted structure Candidate"
            )
        residue_axis = associations.entries[0].residue_axis
        annotation = self._adapter.annotate(
            residue_axis,
            subject=subject,
        )
        return {"annotations": annotation}


class SecondaryStructureExtractOperation:
    """Extract the canonical SS8 track without crossing a provider seam."""

    def __init__(self, resources: OperationResources) -> None:
        self._resources = resources

    def execute(self, call: OperationCall) -> dict[str, Any]:
        annotation = _annotation_input(call.inputs)
        with self._resources.engine_invocation():
            track = StructureAnnotationTrack(
                subject=annotation.subject,
                layout=annotation.layout,
                values=tuple(
                    "C" if value == "P" else value
                    for value in annotation.secondary_structure
                ),
            )
        return {"secondary_structure_track": track}


class SASAComputeOperation:
    """Extract canonical DSSP accessibility without a provider Adapter."""

    def __init__(self, resources: OperationResources) -> None:
        self._resources = resources

    def execute(self, call: OperationCall) -> dict[str, Any]:
        annotation = _annotation_input(call.inputs)
        with self._resources.engine_invocation():
            track = StructureAnnotationTrack(
                subject=annotation.subject,
                layout=annotation.layout,
                values=annotation.sasa,
            )
        return {"sasa_track": track}


class ApplySecondaryStructureToPromptOperation:
    """Apply one exact annotation SS8 track to a ProteinPrompt."""

    def __init__(self, resources: OperationResources) -> None:
        self._resources = resources

    def execute(self, call: OperationCall) -> dict[str, Any]:
        prompt = call.inputs["protein_prompt"].value
        track = call.inputs["secondary_structure_track"].value
        if prompt.target_layout != track.layout:
            raise ValueError(
                "Prompt and secondary-structure track layouts must be exactly equal"
            )
        with self._resources.engine_invocation():
            values: list[str | None] = []
            for value in track.values:
                if value not in _ANNOTATION_TO_PROMPT_SS:
                    raise ValueError(
                        "annotation secondary structure uses an unsupported symbol"
                    )
                values.append(_ANNOTATION_TO_PROMPT_SS[value])
            updated = replace(
                prompt,
                secondary_structure_track=ResidueTrack(values, None),
            )
        return {"protein_prompt": updated}


class ApplySASAToPromptOperation:
    """Apply exact DSSP solvent accessibility to a ProteinPrompt."""

    def __init__(self, resources: OperationResources) -> None:
        self._resources = resources

    def execute(self, call: OperationCall) -> dict[str, Any]:
        prompt = call.inputs["protein_prompt"].value
        track = call.inputs["sasa_track"].value
        if prompt.target_layout != track.layout:
            raise ValueError(
                "Prompt and SASA track layouts must be exactly equal"
            )
        with self._resources.engine_invocation():
            updated = replace(
                prompt,
                sasa_track=ResidueTrack(track.values, None),
            )
        return {"protein_prompt": updated}


class ExpectedSecondaryStructureFromPromptOperation:
    """Project Prompt conditioning as an expected annotation SS8 track."""

    def __init__(self, resources: OperationResources) -> None:
        self._resources = resources

    def execute(self, call: OperationCall) -> dict[str, Any]:
        prompt = call.inputs["protein_prompt"].value
        if prompt.target_layout is None:
            raise ValueError("ProteinPrompt must carry an exact target layout")
        if prompt.secondary_structure_track is None:
            raise ValueError(
                "ProteinPrompt must carry a secondary-structure track"
            )
        reference = _singleton_candidate_reference(
            call,
            port_name="references",
        )
        with self._resources.engine_invocation():
            values: list[str] = []
            for value in prompt.secondary_structure_track.values:
                if value not in _PROMPT_TO_ANNOTATION_SS:
                    raise ValueError(
                        "Prompt secondary structure uses an unsupported symbol"
                    )
                values.append(_PROMPT_TO_ANNOTATION_SS[value])
            track = StructureAnnotationTrack(
                subject=reference,
                layout=prompt.target_layout,
                values=tuple(values),
            )
        return {"secondary_structure_track": track}


class SecondaryStructureAgreementOperation:
    """Compute one exact SS8 agreement Observation directly."""

    def __init__(
        self,
        *,
        resources: OperationResources,
        method: ExactContractReference,
        produced_observation: ResolvedProducedObservation,
    ) -> None:
        self._resources = resources
        self._method = method
        self._produced_observation = produced_observation

    def execute(self, call: OperationCall) -> dict[str, Any]:
        inputs = call.inputs
        expected = inputs["expected"].value
        observed = inputs["observed"].value
        subject_reference = _singleton_candidate_reference(
            call,
            port_name="subjects",
        )
        reference_reference = _singleton_candidate_reference(
            call,
            port_name="references",
        )
        associations = inputs["subject_residue_axes"].value
        if (
            len(associations.entries) != 1
            or associations.entries[0].subject != subject_reference
        ):
            raise ValueError(
                "subject_residue_axes must contain one exact resolved "
                "residue-axis association for the admitted subject Candidate"
            )
        residue_axis = associations.entries[0].residue_axis
        admitted_axis = inputs["subject_residue_axes"].scientific_axes[0]
        if observed.subject != subject_reference:
            raise ValueError(
                "observed track subject must equal the admitted subject Candidate"
            )
        if expected.subject != reference_reference:
            raise ValueError(
                "expected track subject must equal the admitted reference Candidate"
            )
        if expected.layout != observed.layout:
            raise ValueError(
                "agreement tracks must carry one identical exact layout"
            )
        if residue_axis.layout != observed.layout:
            raise ValueError(
                "agreement tracks must equal the authoritative subject "
                "residue-axis layout"
            )
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
            produced = self._produced_observation
            profile = cast(
                PairwiseContextProfile,
                produced.context_profile,
            )
            observation = ScoreObservation(
                subject=subject_reference,
                metric=produced.metric,
                method=self._method,
                context=PairwiseObservationContext(
                    subject=PairwiseParticipant(
                        role="subject",
                        candidate=subject_reference,
                    ),
                    reference=PairwiseParticipant(
                        role="reference",
                        candidate=reference_reference,
                    ),
                    pairing_mode=profile.pairing_mode,
                    normalization=profile.normalization,
                ),
                value=agreement,
                residue_axis=admitted_axis,
                source_partition=produced.output_partition,
            )
        return {
            "scores": ScoreCollection(
                collection_id="structure-annotation-agreement",
                entries=[observation],
            )
        }
