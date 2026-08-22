"""Provider-independent construction of paired folding outputs."""

from __future__ import annotations

from dataclasses import dataclass
from typing import cast

from core.operation import (
    AdmittedPort,
)
from datatypes.candidate import (
    Candidate,
    CandidateCollection,
    CandidateDataReference,
)
from datatypes.exact_reference import ExactContractReference
from datatypes.residue import ResidueLayout
from datatypes.sequence import ProteinSequence
from datatypes.structure import ProteinStructure
from datatypes.residue import (
    residue_identity_chain,
    validate_residue_layout,
)
from datatypes.prediction import (
    PendingConfidenceFact,
    PredictionResidueAxis,
)
from modules.structure_prediction.port_types import (
    confidence_output_identity_intent,
)


_FOLDING_SEQUENCE_ALPHABET = frozenset("ACDEFGHIKLMNPQRSTVWY")


@dataclass(frozen=True, slots=True)
class FoldingParent:
    """One admitted folding parent in its canonical input slot."""

    slot: int
    candidate: Candidate
    sequence: ProteinSequence
    reference: CandidateDataReference
    prediction_axis: PredictionResidueAxis


@dataclass(frozen=True, slots=True)
class CompletedFoldingSample:
    """One canonical Provider observation assigned to an output slot."""

    parent_slot: int
    sample_slot: int
    structure: ProteinStructure
    per_residue_plddt: tuple[float | None, ...]
    ptm: float | None = None
    pae: tuple[tuple[float, ...], ...] | None = None
    effective_call_seed: int | None = None
    num_steps: int | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "per_residue_plddt",
            tuple(self.per_residue_plddt),
        )
        if self.pae is not None:
            object.__setattr__(
                self,
                "pae",
                tuple(tuple(row) for row in self.pae),
            )


@dataclass(frozen=True, slots=True)
class CompletedFoldingSampleBatch:
    """One closed population of completed folding samples."""

    samples: tuple[CompletedFoldingSample, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "samples", tuple(self.samples))


def _prediction_axis(
    sequence: ProteinSequence,
    source: CandidateDataReference,
) -> PredictionResidueAxis:
    if any(
        symbol not in _FOLDING_SEQUENCE_ALPHABET
        for symbol in sequence.sequence
    ):
        raise ValueError("folding requires a canonical protein sequence")
    residue_ids = (
        tuple(sequence.residue_ids)
        if sequence.residue_ids is not None
        else tuple(
            f"A:{index}"
            for index in range(1, len(sequence.sequence) + 1)
        )
    )
    chains = tuple(
        dict.fromkeys(
            residue_identity_chain(
                residue_id,
                subject="folding prediction residue identity",
            )
            for residue_id in residue_ids
        )
    )
    if len(chains) != 1:
        raise ValueError("folding requires a single-chain protein sequence")
    layout = validate_residue_layout(
        ResidueLayout(
            chain_id=chains[0],
            length=len(sequence.sequence),
            residue_ids=residue_ids,
        ),
        subject="folding prediction residue axis",
    )
    return PredictionResidueAxis(
        source=source,
        layout=layout,
        sequence=ProteinSequence(
            sequence=sequence.sequence,
            residue_ids=residue_ids,
        ),
    )


class FoldingOutputConstruction:
    """Own folding parent intake and construct one complete paired output."""

    def __init__(
        self,
        *,
        parent_record: AdmittedPort,
        sample_count: int,
        observation_method: ExactContractReference,
    ) -> None:
        collection = parent_record.value
        if collection.item_type != "protein.sequence" or not collection.items:
            raise ValueError(
                "folding requires non-empty protein sequence Candidates"
            )
        parents: list[FoldingParent] = []
        for slot, (candidate, reference) in enumerate(
            zip(
                collection.items,
                parent_record.candidate_data,
                strict=True,
            )
        ):
            sequence = cast(ProteinSequence, candidate.data)
            parents.append(
                FoldingParent(
                    slot=slot,
                    candidate=candidate,
                    sequence=sequence,
                    reference=reference,
                    prediction_axis=_prediction_axis(sequence, reference),
                )
            )
        self.parents = tuple(parents)
        self._sample_count = sample_count
        self._observation_method = observation_method

    @staticmethod
    def _pending_confidence_fact(
        *,
        candidate_id: str,
        output_slot: int,
        sample: CompletedFoldingSample,
        prediction_axis: PredictionResidueAxis,
    ) -> PendingConfidenceFact:
        return PendingConfidenceFact(
            candidate_id=candidate_id,
            output_role="structure_candidates",
            output_slot=output_slot,
            structure=sample.structure,
            prediction_axis=prediction_axis,
            plddt_per_residue=sample.per_residue_plddt,
            ptm=sample.ptm,
            pae=sample.pae,
        )

    @staticmethod
    def _metadata(
        sample: CompletedFoldingSample,
    ) -> dict[str, int | str]:
        metadata: dict[str, int | str] = {
            "parent_index": sample.parent_slot,
            "sample_index": sample.sample_slot,
        }
        if sample.effective_call_seed is not None:
            metadata["effective_call_seed"] = sample.effective_call_seed
        if sample.num_steps is not None:
            metadata["num_steps"] = sample.num_steps
        return metadata

    def construct(
        self,
        completed: CompletedFoldingSampleBatch,
    ) -> dict[str, object]:
        expected_slots = {
            (parent.slot, sample_slot)
            for parent in self.parents
            for sample_slot in range(self._sample_count)
        }
        samples_by_slot: dict[
            tuple[int, int], CompletedFoldingSample
        ] = {}
        for sample in completed.samples:
            slot = (sample.parent_slot, sample.sample_slot)
            if slot in samples_by_slot:
                raise ValueError(
                    "completed folding samples contain a duplicate "
                    "parent/sample slot"
                )
            samples_by_slot[slot] = sample
        if set(samples_by_slot) != expected_slots:
            raise ValueError(
                "completed folding samples do not exactly close the declared "
                "parent/sample slots"
            )

        candidates: list[Candidate] = []
        confidence_facts: list[PendingConfidenceFact] = []
        for parent in self.parents:
            for sample_slot in range(self._sample_count):
                sample = samples_by_slot[(parent.slot, sample_slot)]
                candidate_id = (
                    f"fold-parent-{parent.slot}-sample-{sample_slot}"
                )
                fact = self._pending_confidence_fact(
                    candidate_id=candidate_id,
                    output_slot=len(candidates),
                    sample=sample,
                    prediction_axis=parent.prediction_axis,
                )
                candidates.append(
                    Candidate(
                        candidate_id=candidate_id,
                        data=sample.structure,
                        parent_ids=(parent.candidate.candidate_id,),
                        metadata=self._metadata(sample),
                    )
                )
                confidence_facts.append(fact)

        return {
            "structure_candidates": CandidateCollection(
                "folding-structure-candidates",
                "protein.structure",
                tuple(candidates),
            ),
            "confidence_facts": confidence_output_identity_intent(
                observation_method=self._observation_method,
                pending_facts=tuple(confidence_facts),
            ),
        }
