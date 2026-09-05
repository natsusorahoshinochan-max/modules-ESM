"""Canonical Scientific Operations for the structure-annotation package."""

from __future__ import annotations

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
from datatypes.residue import (
    CandidateResidueTrack,
    ResidueLayout,
    ResidueTrack,
)
from datatypes.structure import ResolvedStructureResidueAxis


_PROMPT_TO_OBSERVED_SS = {
    "G": "G",
    "H": "H",
    "I": "I",
    "T": "T",
    "E": "E",
    "B": "B",
    "S": "S",
    "C": "C",
    None: None,
}


class _DSSPAdapter(Protocol):
    """Canonical-only internal seam used by the DSSP Operation."""

    def annotate(
        self,
        residue_axis: ResolvedStructureResidueAxis,
        *,
        subject: CandidateDataReference,
    ) -> tuple[CandidateResidueTrack[str], CandidateResidueTrack[float]]: ...


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
        secondary_structure, sasa = self._adapter.annotate(
            residue_axis,
            subject=subject,
        )
        return {
            "secondary_structure": secondary_structure,
            "sasa": sasa,
        }


class ObservedToConditioningOperation:
    """Project one observed annotation track to residue conditioning.

    Exactly one observed input may be connected; the Candidate subject is
    explicitly dropped and no ProteinPrompt is rebuilt.
    """

    def __init__(self, resources: OperationResources) -> None:
        self._resources = resources

    def execute(self, call: OperationCall) -> dict[str, Any]:
        secondary_port = call.inputs.get("secondary_structure")
        sasa_port = call.inputs.get("sasa")
        if bool(secondary_port) == bool(sasa_port):
            raise ValueError(
                "observed_to_conditioning requires exactly one observed "
                "input connected"
            )
        with self._resources.engine_invocation():
            if secondary_port:
                track = secondary_port.value.track
                return {
                    "secondary_structure": ResidueTrack(
                        track.layout,
                        track.values,
                    )
                }
            track = sasa_port.value.track
            return {"sasa": ResidueTrack(track.layout, track.values)}


class ExpectedSecondaryStructureFromPromptOperation:
    """Project Prompt conditioning as an expected observed SS8 track."""

    def __init__(self, resources: OperationResources) -> None:
        self._resources = resources

    def execute(self, call: OperationCall) -> dict[str, Any]:
        prompt = call.inputs["protein_prompt"].value
        if prompt.secondary_structure is None:
            raise ValueError(
                "ProteinPrompt must carry a secondary-structure track"
            )
        reference = _singleton_candidate_reference(
            call,
            port_name="references",
        )
        with self._resources.engine_invocation():
            track = CandidateResidueTrack(
                subject=reference,
                track=ResidueTrack(
                    cast(ResidueLayout, prompt.layout),
                    tuple(
                        _PROMPT_TO_OBSERVED_SS[value]
                        for value in prompt.secondary_structure
                    ),
                ),
            )
        return {"secondary_structure": track}


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
        if expected.track.layout != observed.track.layout:
            raise ValueError(
                "agreement tracks must carry one identical exact layout"
            )
        if residue_axis.layout != observed.track.layout:
            raise ValueError(
                "agreement tracks must equal the authoritative subject "
                "residue-axis layout"
            )
        with self._resources.engine_invocation():
            compared = [
                (expected_value, observed_value)
                for expected_value, observed_value in zip(
                    expected.track.values,
                    observed.track.values,
                    strict=True,
                )
                if expected_value is not None and observed_value is not None
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
