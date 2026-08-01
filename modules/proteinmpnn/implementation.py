"""Canonical ProteinMPNN Scientific Operation implementations."""

from __future__ import annotations

from collections.abc import Mapping
import hashlib
from typing import Any

from core import OperationCall, RunResources
from datatypes import (
    Candidate,
    CandidateCollection,
    ExactContractReference,
    IntrinsicObservationContext,
    ProteinMPNNConstraints,
    ProteinSequence,
    ProteinStructure,
    ScoreCollection,
    ScoreObservation,
)

from .adapter import LocalProteinMPNNAdapter
from .domain import (
    author_constraints,
    normalize_design_parameters,
    random_fixed_positions,
)


class ProteinMPNNConstraintsImplementation:
    """Author one complete identity-addressed constraint value."""

    def __init__(self, resources: RunResources) -> None:
        self._resources = resources

    def execute(self, call: OperationCall) -> dict[str, Any]:
        if set(call.inputs) != {"layout"} or call.binding_parameters:
            raise ValueError(
                "constraint authoring requires one explicit residue layout"
            )
        with self._resources.engine_invocation():
            constraints = author_constraints(
                call.inputs["layout"],
                call.node_parameters,
            )
        return {"constraints": constraints}


class ProteinMPNNRandomFixedPositionsImplementation:
    """Choose a stable identity-addressed fixed-residue subset."""

    def __init__(self, resources: RunResources) -> None:
        self._resources = resources

    def execute(self, call: OperationCall) -> dict[str, Any]:
        if (
            set(call.inputs) != {"layout"}
            or set(call.node_parameters) != {"effective_seed", "fraction"}
            or call.binding_parameters
        ):
            raise ValueError(
                "random fixed-position selection requires resolved parameters"
            )
        with self._resources.engine_invocation():
            constraints = random_fixed_positions(
                call.inputs["layout"],
                effective_seed=call.node_parameters["effective_seed"],
                fraction=call.node_parameters["fraction"],
            )
        return {"constraints": constraints}


class ProteinMPNNDesignImplementation:
    """Create sequence Candidates while preserving exact parent lineage."""

    def __init__(
        self,
        *,
        resources: RunResources,
        adapter: LocalProteinMPNNAdapter,
    ) -> None:
        self._resources = resources
        self._adapter = adapter

    def _parents(
        self,
        inputs: Mapping[str, Any],
    ) -> list[tuple[ProteinStructure, tuple[str, ...]]]:
        allowed = {
            "structure",
            "structure_candidates",
            "sequence",
            "constraints",
        }
        if not set(inputs) <= allowed:
            raise ValueError("ProteinMPNN design received undeclared inputs")
        has_structure = "structure" in inputs
        has_collection = "structure_candidates" in inputs
        if has_structure == has_collection:
            raise ValueError(
                "ProteinMPNN design requires exactly one structure input mode"
            )
        if has_structure:
            structure = inputs["structure"]
            if type(structure) is not ProteinStructure:
                raise ValueError("structure input is incomplete")
            return [(structure, ())]
        collection = inputs["structure_candidates"]
        if (
            type(collection) is not CandidateCollection
            or collection.item_type != "protein.structure"
            or not collection.items
        ):
            raise ValueError(
                "structure_candidates must be non-empty protein structures"
            )
        parent_ids: set[str] = set()
        parents: list[tuple[ProteinStructure, tuple[str, ...]]] = []
        for candidate in collection.items:
            if (
                type(candidate) is not Candidate
                or type(candidate.data) is not ProteinStructure
                or not candidate.candidate_id
                or candidate.candidate_id in parent_ids
            ):
                raise ValueError(
                    "structure_candidates contain incomplete or duplicate parents"
                )
            parent_ids.add(candidate.candidate_id)
            parents.append((candidate.data, (candidate.candidate_id,)))
        return parents

    @staticmethod
    def _parameters(
        call: OperationCall,
    ) -> tuple[int, int, float, float]:
        normalized = normalize_design_parameters(
            call.node_parameters,
            call.binding_parameters,
        )
        return (
            int(normalized["effective_seed"]),
            int(normalized["num_sequences"]),
            float(normalized["temperature"]),
            float(normalized["backbone_noise"]),
        )

    @staticmethod
    def _call_seed(
        effective_seed: int,
        parent_content_digest: str,
        parent_slot: int,
    ) -> int:
        digest = hashlib.sha256(
            (
                "protein-workbench-proteinmpnn-parent-seed/v2\0"
                f"{effective_seed}\0"
                f"{parent_slot}\0"
                f"{parent_content_digest}"
            ).encode()
        ).digest()
        return int.from_bytes(digest[:7], "big") % 9_007_199_254_740_992

    @staticmethod
    def _parent_content_digests(
        call: OperationCall,
        parents: list[tuple[ProteinStructure, tuple[str, ...]]],
    ) -> tuple[str, ...]:
        if "structure" in call.inputs:
            admitted = call.input_content_digests.get("structure")
            if (
                admitted is None
                or admitted.port_type_id != "protein.structure"
                or len(admitted.value_content_digests) != 1
                or admitted.candidate_data
            ):
                raise ValueError(
                    "ProteinMPNN design requires the admitted structure "
                    "content identity"
                )
            return admitted.value_content_digests

        admitted = call.input_content_digests.get("structure_candidates")
        if (
            admitted is None
            or admitted.port_type_id != "candidate.collection"
        ):
            raise ValueError(
                "ProteinMPNN design requires admitted structure Candidate "
                "content identities"
            )
        by_candidate_id = {
            item.candidate_id: item
            for item in admitted.candidate_data
        }
        expected_ids = {
            parent_ids[0]
            for _, parent_ids in parents
            if len(parent_ids) == 1
        }
        if (
            len(by_candidate_id) != len(admitted.candidate_data)
            or len(expected_ids) != len(parents)
            or set(by_candidate_id) != expected_ids
            or any(
                item.data_type_id != "protein.structure"
                for item in by_candidate_id.values()
            )
        ):
            raise ValueError(
                "ProteinMPNN structure Candidate content identities are "
                "incomplete"
            )
        return tuple(
            by_candidate_id[parent_ids[0]].content_digest
            for _, parent_ids in parents
        )

    @staticmethod
    def _constraint_digest(call: OperationCall) -> str | None:
        admitted = call.input_content_digests.get("constraints")
        if admitted is None:
            return None
        if len(admitted.value_content_digests) != 1:
            raise RuntimeError(
                "ProteinMPNN constraints input content identity is incomplete"
            )
        return admitted.value_content_digests[0]

    def execute(self, call: OperationCall) -> dict[str, Any]:
        parents = self._parents(call.inputs)
        parent_content_digests = self._parent_content_digests(call, parents)
        seed, count, temperature, noise = self._parameters(call)
        reference = call.inputs.get("sequence")
        if reference is not None and type(reference) is not ProteinSequence:
            raise ValueError("sequence input must be a complete ProteinSequence")
        constraints = call.inputs.get("constraints")
        if (
            constraints is not None
            and type(constraints) is not ProteinMPNNConstraints
        ):
            raise ValueError(
                "constraints input must be complete ProteinMPNN constraints"
            )
        constraint_digest = self._constraint_digest(call)
        candidates: list[Candidate] = []
        for parent_index, (structure, parent_ids) in enumerate(parents):
            call_seed = self._call_seed(
                seed,
                parent_content_digests[parent_index],
                parent_index,
            )
            sequences = self._adapter.design(
                structure=structure,
                num_sequences=count,
                temperature=temperature,
                backbone_noise=noise,
                seed=call_seed,
                constraints=constraints,
                reference_sequence=reference,
                engine_role=f"design_parent_{parent_index}",
            )
            if len(sequences) != count:
                raise RuntimeError(
                    "ProteinMPNN design returned an incomplete child set"
                )
            for sample_index, sequence in enumerate(sequences):
                candidates.append(
                    Candidate(
                        (
                            f"proteinmpnn-parent-{parent_index}-"
                            f"sample-{sample_index}"
                        ),
                        sequence,
                        parent_ids,
                        {
                            "parent_index": parent_index,
                            "sample_index": sample_index,
                            "effective_seed": seed,
                            "effective_call_seed": call_seed,
                            "num_sequences": count,
                            "temperature": temperature,
                            "backbone_noise": noise,
                            "constraint_digest": constraint_digest,
                        },
                    )
                )
        if len(candidates) != len(parents) * count:
            raise RuntimeError("ProteinMPNN design children are incomplete")
        for _, parent_ids in parents:
            children = [
                candidate
                for candidate in candidates
                if candidate.parent_ids == parent_ids
            ]
            if len(children) != count:
                raise RuntimeError(
                    "ProteinMPNN design parent relationship is incomplete"
                )
        return {
            "sequence_candidates": CandidateCollection(
                "proteinmpnn-sequence-candidates",
                "protein.sequence",
                candidates,
            )
        }


class ProteinMPNNScoreImplementation:
    """Observe one exact sequence Candidate on its exact parent structure."""

    def __init__(
        self,
        *,
        adapter: LocalProteinMPNNAdapter,
        method: ExactContractReference,
        metric: ExactContractReference,
    ) -> None:
        self._adapter = adapter
        self._method = method
        self._metric = metric

    @staticmethod
    def _subject(
        inputs: Mapping[str, Any],
    ) -> tuple[Candidate, Candidate]:
        if set(inputs) != {
            "structure_candidates",
            "sequence_candidates",
        }:
            raise ValueError(
                "ProteinMPNN scoring requires exact structure and sequence "
                "Candidate inputs"
            )
        structures = inputs["structure_candidates"]
        sequences = inputs["sequence_candidates"]
        if (
            type(structures) is not CandidateCollection
            or structures.item_type != "protein.structure"
            or len(structures.items) != 1
            or type(sequences) is not CandidateCollection
            or sequences.item_type != "protein.sequence"
            or len(sequences.items) != 1
        ):
            raise ValueError(
                "ProteinMPNN scoring requires one structure Candidate and "
                "one sequence Candidate"
            )
        structure = structures.items[0]
        sequence = sequences.items[0]
        if (
            type(structure) is not Candidate
            or not structure.candidate_id
            or type(structure.data) is not ProteinStructure
            or type(sequence) is not Candidate
            or not sequence.candidate_id
            or type(sequence.data) is not ProteinSequence
            or sequence.parent_ids != (structure.candidate_id,)
        ):
            raise ValueError(
                "ProteinMPNN scoring inputs do not identify one sequence "
                "Candidate and its exact parent structure"
            )
        return structure, sequence

    def execute(self, call: OperationCall) -> dict[str, Any]:
        if call.node_parameters or call.binding_parameters:
            raise ValueError(
                "ProteinMPNN scoring accepts no Workflow parameters"
            )
        structure_candidate, sequence_candidate = self._subject(call.inputs)
        structure = structure_candidate.data
        sequence = sequence_candidate.data
        assert type(structure) is ProteinStructure
        assert type(sequence) is ProteinSequence
        score = self._adapter.score(
            structure=structure,
            sequence=sequence,
        )
        observation = ScoreObservation(
            candidate_id=sequence_candidate.candidate_id,
            metric=self._metric,
            method=self._method,
            context=IntrinsicObservationContext(),
            value=score,
        )
        return {
            "scores": ScoreCollection(
                "proteinmpnn-score-observations",
                [observation],
            )
        }
