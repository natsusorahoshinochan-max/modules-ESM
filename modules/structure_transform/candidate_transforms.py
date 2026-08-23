"""Candidate-aware structure transforms joined by exact data references."""

from __future__ import annotations

from typing import Mapping, cast

from core.operation import (
    OperationCall,
    OperationResources,
)
from datatypes.candidate import (
    Candidate,
    CandidateCollection,
    CandidateDataReference,
)
from datatypes.residue import ModifiedResidueNormalizationCollection

from .csh_normalization import normalize_csh_parent_span
from .domain import (
    CandidateNormalizationFactCollection,
    CandidateModifiedResidueNormalizationAssociation,
    CandidateModifiedResidueNormalizationAssociations,
    CandidateResolvedResidueAxisAssociation,
    CandidateResolvedResidueAxisAssociations,
    PendingCandidateNormalizationFact,
)
from ._candidate_association_codecs import (
    candidate_normalization_output_identity_intent,
)
from .projections import extract_sequence, select_chains
from .residue_axis import resolve_residue_axis


def _structure_candidate_parents(value: object) -> list[Candidate]:
    collection = cast(CandidateCollection, value)
    return list(collection.items)


def _candidate_structures_and_references(
    call: OperationCall,
) -> tuple[tuple[Candidate, CandidateDataReference], ...]:
    admitted = call.inputs["structure_candidates"]
    collection = cast(CandidateCollection, admitted.value)
    references_by_id = {
        reference.candidate_id: reference
        for reference in admitted.candidate_data
    }
    return tuple(
        (candidate, references_by_id[candidate.candidate_id])
        for candidate in collection.items
    )


def _candidate_normalizations_by_id(
    value: object,
    references_by_id: Mapping[str, CandidateDataReference],
) -> dict[str, ModifiedResidueNormalizationCollection]:
    associations = cast(CandidateModifiedResidueNormalizationAssociations, value)
    entries_by_id = {
        entry.subject.candidate_id: entry
        for entry in associations.entries
    }
    if set(entries_by_id) != set(references_by_id) or any(
        entries_by_id[candidate_id].subject != reference
        for candidate_id, reference in references_by_id.items()
    ):
        raise ValueError(
            "Candidate residue-axis resolution requires complete exact "
            "Candidate references for modified-residue normalizations"
        )
    return {
        candidate_id: entries_by_id[candidate_id].normalizations
        for candidate_id in references_by_id
    }


class SelectCandidateChainsImplementation:
    """Select exact chains while preserving Candidate lineage."""

    def __init__(self, run_resources: OperationResources) -> None:
        self._run_resources = run_resources

    def execute(self, call: OperationCall) -> dict[str, object]:
        parents = _structure_candidate_parents(
            call.inputs["structure_candidates"].value
        )
        chain_ids = call.node_parameters["chain_ids"]
        with self._run_resources.engine_invocation():
            children = tuple(
                Candidate(
                    candidate_id=f"selected-structure-{index}",
                    data=select_chains(parent.data, chain_ids),
                    parent_ids=[parent.candidate_id],
                    metadata={
                        "transform": (
                            "structure_transform.select_candidate_chains"
                        ),
                        "parent_index": index,
                        "chain_ids": list(chain_ids),
                    },
                )
                for index, parent in enumerate(parents)
            )
            return {
                "structure_candidates": CandidateCollection(
                    collection_id="selected-structure-candidates",
                    item_type="protein.structure",
                    items=children,
                )
            }


class ExtractSequenceCandidatesImplementation:
    """Project exact-reference-associated axes into sequence Candidates."""

    def __init__(self, run_resources: OperationResources) -> None:
        self._run_resources = run_resources

    def execute(self, call: OperationCall) -> dict[str, object]:
        candidates_and_references = _candidate_structures_and_references(call)
        residue_axes = cast(
            CandidateResolvedResidueAxisAssociations,
            call.inputs["residue_axes"].value,
        )
        axes_by_id = {
            entry.subject.candidate_id: entry
            for entry in residue_axes.entries
        }
        references_by_id = {
            reference.candidate_id: reference
            for _, reference in candidates_and_references
        }
        if set(axes_by_id) != set(references_by_id) or any(
            axes_by_id[candidate_id].subject != reference
            for candidate_id, reference in references_by_id.items()
        ):
            raise ValueError(
                "Candidate sequence extraction requires complete exact "
                "Candidate references"
            )
        with self._run_resources.engine_invocation():
            return {
                "sequence_candidates": CandidateCollection(
                    collection_id="extracted-sequence-candidates",
                    item_type="protein.sequence",
                    items=tuple(
                        Candidate(
                            candidate_id=f"extracted-sequence-{index}",
                            data=extract_sequence(
                                axes_by_id[
                                    reference.candidate_id
                                ].residue_axis
                            ),
                            parent_ids=[candidate.candidate_id],
                            metadata={
                                "transform": (
                                    "structure_transform."
                                    "extract_sequence_candidates"
                                ),
                                "parent_index": index,
                            },
                        )
                        for index, (candidate, reference) in enumerate(
                            candidates_and_references
                        )
                    ),
                )
            }


class NormalizeCshParentSpanCandidatesImplementation:
    """Normalize CSH Candidates and emit output-slot-keyed facts."""

    def __init__(self, run_resources: OperationResources) -> None:
        self._run_resources = run_resources

    def execute(self, call: OperationCall) -> dict[str, object]:
        candidates_and_references = _candidate_structures_and_references(call)
        normalized_candidates: list[Candidate] = []
        facts: list[PendingCandidateNormalizationFact] = []
        with self._run_resources.engine_invocation():
            for output_slot, (candidate, _) in enumerate(
                candidates_and_references
            ):
                normalized, normalizations = normalize_csh_parent_span(
                    candidate.data
                )
                candidate_id = f"normalized-csh-{output_slot}"
                facts.append(
                    PendingCandidateNormalizationFact(
                        candidate_id=candidate_id,
                        output_role="structure_candidates",
                        output_slot=output_slot,
                        structure=normalized,
                        normalizations=normalizations,
                    )
                )
                normalized_candidates.append(
                    Candidate(
                        candidate_id=candidate_id,
                        data=normalized,
                        parent_ids=(candidate.candidate_id,),
                        metadata={
                            "transform": (
                                "structure_transform."
                                "normalize_csh_parent_span_candidates"
                            ),
                        },
                    )
                )
        return {
            "structure_candidates": CandidateCollection(
                collection_id="normalized-csh-structure-candidates",
                item_type="protein.structure",
                items=tuple(normalized_candidates),
            ),
            "normalization_facts": candidate_normalization_output_identity_intent(
                tuple(facts)
            ),
        }


class MaterializeCandidateNormalizationsImplementation:
    """Join normalization facts to admitted Candidate content exactly."""

    def __init__(self, run_resources: OperationResources) -> None:
        self._run_resources = run_resources

    def execute(self, call: OperationCall) -> dict[str, object]:
        candidates_and_references = _candidate_structures_and_references(call)
        facts = cast(
            CandidateNormalizationFactCollection,
            call.inputs["normalization_facts"].value,
        )
        facts_by_key = {
            fact.normalization_key: fact
            for fact in facts.entries
        }
        candidate_keys = {
            candidate.metadata.get("normalization_key")
            for candidate, _ in candidates_and_references
        }
        if (
            None in candidate_keys
            or len(candidate_keys) != len(candidates_and_references)
            or candidate_keys != set(facts_by_key)
        ):
            raise ValueError(
                "Candidates and normalization facts must form one complete key set"
            )

        associations: list[
            CandidateModifiedResidueNormalizationAssociation
        ] = []
        with self._run_resources.engine_invocation():
            for output_slot, (candidate, reference) in enumerate(
                candidates_and_references
            ):
                key = candidate.metadata["normalization_key"]
                fact = facts_by_key[key]
                output_port = candidate.metadata.get("output_port")
                sample_slot = candidate.metadata.get("sample_slot")
                if (
                    output_port != "structure_candidates"
                    or sample_slot != f"0:{output_slot}"
                ):
                    raise ValueError(
                        "normalized Candidate output slot metadata is incomplete"
                    )
                if fact.structure_content_digest != reference.content_digest:
                    raise ValueError(
                        "normalization fact contradicts admitted Candidate content"
                    )
                associations.append(
                    CandidateModifiedResidueNormalizationAssociation(
                        subject=reference,
                        normalizations=fact.normalizations,
                    )
                )
        return {
            "modified_residue_normalizations": (
                CandidateModifiedResidueNormalizationAssociations(
                    tuple(associations)
                )
            )
        }


class ProjectSingleResidueAxisImplementation:
    """Project the only exact Candidate residue-axis association."""

    def __init__(self, run_resources: OperationResources) -> None:
        self._run_resources = run_resources

    def execute(self, call: OperationCall) -> dict[str, object]:
        candidates_and_references = _candidate_structures_and_references(call)
        axes = cast(
            CandidateResolvedResidueAxisAssociations,
            call.inputs["residue_axes"].value,
        )
        if (
            len(candidates_and_references) != 1
            or len(axes.entries) != 1
            or axes.entries[0].subject != candidates_and_references[0][1]
        ):
            raise ValueError(
                "single residue-axis projection requires one exact association"
            )
        with self._run_resources.engine_invocation():
            return {"residue_axis": axes.entries[0].residue_axis}


class ResolveCandidateResidueAxesImplementation:
    """Resolve residue axes and associate them by exact Candidate reference."""

    def __init__(self, run_resources: OperationResources) -> None:
        self._run_resources = run_resources

    def execute(self, call: OperationCall) -> dict[str, object]:
        candidates_and_references = _candidate_structures_and_references(call)
        references_by_id = {
            reference.candidate_id: reference
            for _, reference in candidates_and_references
        }
        normalizations_by_id = (
            _candidate_normalizations_by_id(
                call.inputs["modified_residue_normalizations"].value,
                references_by_id,
            )
            if "modified_residue_normalizations" in call.inputs
            else {}
        )
        with self._run_resources.engine_invocation():
            return {
                "residue_axes": CandidateResolvedResidueAxisAssociations(
                    entries=tuple(
                        CandidateResolvedResidueAxisAssociation(
                            subject=reference,
                            residue_axis=resolve_residue_axis(
                                candidate.data,
                                normalizations_by_id.get(
                                    candidate.candidate_id
                                ),
                            ),
                        )
                        for candidate, reference
                        in candidates_and_references
                    )
                )
            }
