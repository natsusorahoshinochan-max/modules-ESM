"""v2 ProteinMPNN constraint and sequence-design implementations."""

from __future__ import annotations

from collections.abc import Mapping
import hashlib
from typing import Any

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

from .domain import (
    author_constraints,
    normalize_design_parameters,
    random_fixed_positions,
)
from .v2_adapter import (
    PROTEINMPNN_MODEL,
    prepare_design_request,
    prepare_scoring_request,
    provider_for_environment,
    validate_design_result,
    validate_scoring_result,
)


class ProteinMPNNConstraintsImplementation:
    def __init__(
        self,
        run_resources: Any,
        environment: Mapping[str, Any],
        catalog: Any,
    ) -> None:
        self._run_resources = run_resources
        del environment, catalog

    def execute(
        self,
        *,
        inputs: Mapping[str, Any],
        node_parameters: Mapping[str, Any],
        binding_parameters: Mapping[str, Any],
    ) -> dict[str, Any]:
        if set(inputs) != {"layout"} or binding_parameters:
            raise ValueError(
                "constraint authoring requires one explicit residue layout"
            )
        with self._run_resources.engine_invocation(
            engine_identity=(
                "proteinmpnn.constraints.repository_owned/2.1.0"
            ),
        ):
            constraints = author_constraints(
                inputs["layout"],
                node_parameters,
            )
        return {"constraints": constraints}


class ProteinMPNNRandomFixedPositionsImplementation:
    def __init__(
        self,
        run_resources: Any,
        environment: Mapping[str, Any],
        catalog: Any,
    ) -> None:
        self._run_resources = run_resources
        del environment, catalog

    def execute(
        self,
        *,
        inputs: Mapping[str, Any],
        node_parameters: Mapping[str, Any],
        binding_parameters: Mapping[str, Any],
    ) -> dict[str, Any]:
        if (
            set(inputs) != {"layout"}
            or set(node_parameters) != {"effective_seed", "fraction"}
            or binding_parameters
        ):
            raise ValueError(
                "random fixed-position selection requires resolved parameters"
            )
        with self._run_resources.engine_invocation(
            engine_identity=(
                "proteinmpnn.random_fixed_positions."
                "repository_owned/2.1.0"
            ),
        ):
            constraints = random_fixed_positions(
                inputs["layout"],
                effective_seed=node_parameters["effective_seed"],
                fraction=node_parameters["fraction"],
            )
        return {"constraints": constraints}


class ProteinMPNNDesignImplementation:
    def __init__(
        self,
        run_resources: Any,
        environment: Mapping[str, Any],
        catalog: Any,
    ) -> None:
        self._run_resources = run_resources
        self._environment = environment
        self._catalog = catalog

    @staticmethod
    def _parents(
        inputs: Mapping[str, Any],
        node_id: str,
    ) -> list[tuple[Candidate, str]]:
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
            return [(
                Candidate(
                    node_id,
                    structure,
                    [],
                    {"input_mode": "standalone"},
                ),
                "standalone-structure",
            )]
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
        parents: list[tuple[Candidate, str]] = []
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
            parents.append((candidate, candidate.candidate_id))
        return parents

    @staticmethod
    def _parameters(
        node_parameters: Mapping[str, Any],
        binding_parameters: Mapping[str, Any],
    ) -> tuple[int, int, float, float]:
        normalized = normalize_design_parameters(
            node_parameters,
            binding_parameters,
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
        parent: Candidate,
        parent_slot: int,
    ) -> int:
        structure = parent.data
        assert type(structure) is ProteinStructure
        digest = hashlib.sha256(
            (
                "protein-workbench-proteinmpnn-parent-seed/v2\0"
                f"{effective_seed}\0"
                f"{parent_slot}\0"
                + hashlib.sha256(
                    structure.pdb_string.encode()
                ).hexdigest()
            ).encode()
        ).digest()
        return int.from_bytes(digest[:7], "big") % 9_007_199_254_740_992

    def _constraint_digest(
        self,
        constraints: ProteinMPNNConstraints,
    ) -> str:
        port_type = self._catalog.require_port_type(
            "proteinmpnn.constraints",
            "2.1.0",
        )
        return port_type.content_digest(constraints)

    def execute(
        self,
        *,
        inputs: Mapping[str, Any],
        node_parameters: Mapping[str, Any],
        binding_parameters: Mapping[str, Any],
    ) -> dict[str, Any]:
        parents = self._parents(inputs, self._run_resources.node_id)
        seed, count, temperature, noise = self._parameters(
            node_parameters,
            binding_parameters,
        )
        reference = inputs.get("sequence")
        if reference is not None and type(reference) is not ProteinSequence:
            raise ValueError("sequence input must be a complete ProteinSequence")
        constraints = inputs.get("constraints")
        if (
            constraints is not None
            and type(constraints) is not ProteinMPNNConstraints
        ):
            raise ValueError(
                "constraints input must be complete ProteinMPNN constraints"
            )
        candidates: list[Candidate] = []
        for parent_index, (parent, _) in enumerate(parents):
            structure = parent.data
            assert type(structure) is ProteinStructure
            call_seed = self._call_seed(
                seed,
                parent,
                parent_index,
            )
            raw_ids = [
                (
                    f"proteinmpnn-parent-{parent_index}-"
                    f"sample-{sample_index}"
                )
                for sample_index in range(count)
            ]
            with self._run_resources.temporary_directory(
                prefix="proteinmpnn-design-"
            ) as staging_directory:
                provider = provider_for_environment(
                    self._environment,
                    staging_directory=staging_directory,
                )
                request = prepare_design_request(
                    provider=provider,
                    structure=structure,
                    num_sequences=count,
                    temperature=temperature,
                    backbone_noise=noise,
                    seed=call_seed,
                    constraints=constraints,
                    reference_sequence=reference,
                )
                effective_constraints = constraints or ProteinMPNNConstraints(
                    layout=request.target_layout
                )
                constraint_digest = self._constraint_digest(
                    effective_constraints
                )
                with self._run_resources.engine_invocation(
                    engine_role=f"design_parent_{parent_index}",
                    engine_identity=(
                        "proteinmpnn.design.local."
                        "proteinmpnn.design.v_48_020_8907e667"
                    ),
                ):
                    raw_result = provider.design(request)
                sequences, scores = validate_design_result(
                    raw_result,
                    request=request,
                )
            for sample_index, (raw_id, sequence) in enumerate(
                zip(raw_ids, sequences, strict=True)
            ):
                candidates.append(
                    Candidate(
                        raw_id,
                        sequence,
                        [parent.candidate_id],
                        {
                            "model": PROTEINMPNN_MODEL,
                            "parent_index": parent_index,
                            "sample_index": sample_index,
                            "effective_seed": seed,
                            "effective_call_seed": call_seed,
                            "num_sequences": count,
                            "temperature": temperature,
                            "backbone_noise": noise,
                            "constraint_digest": constraint_digest,
                            "residue_identity_mapping": [
                                {
                                    "residue_id": residue_id,
                                    "provider_chain_id": provider_chain_id,
                                    "provider_position": provider_position,
                                }
                                for (
                                    residue_id,
                                    provider_chain_id,
                                    provider_position,
                                ) in request.residue_identity_mapping
                            ],
                        },
                    )
                )
        if len(candidates) != len(parents) * count:
            raise RuntimeError("ProteinMPNN design children are incomplete")
        for parent, _ in parents:
            children = [
                candidate
                for candidate in candidates
                if candidate.parent_ids == [parent.candidate_id]
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
        run_resources: Any,
        environment: Mapping[str, Any],
        catalog: Any,
    ) -> None:
        self._run_resources = run_resources
        self._environment = environment
        self._catalog = catalog

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
            or sequence.parent_ids != [structure.candidate_id]
        ):
            raise ValueError(
                "ProteinMPNN scoring inputs do not identify one sequence "
                "Candidate and its exact parent structure"
            )
        return structure, sequence

    def _contract_reference(
        self,
        kind: str,
        contract_id: str,
    ) -> ExactContractReference:
        contract = self._catalog.require_contract(
            kind,
            contract_id,
            "2.1.0",
        )
        return ExactContractReference(**contract.reference())

    def execute(
        self,
        *,
        inputs: Mapping[str, Any],
        node_parameters: Mapping[str, Any],
        binding_parameters: Mapping[str, Any],
    ) -> dict[str, Any]:
        if node_parameters or binding_parameters:
            raise ValueError(
                "ProteinMPNN scoring accepts no Workflow parameters"
            )
        structure_candidate, sequence_candidate = self._subject(inputs)
        structure = structure_candidate.data
        sequence = sequence_candidate.data
        assert type(structure) is ProteinStructure
        assert type(sequence) is ProteinSequence
        with self._run_resources.temporary_directory(
            prefix="proteinmpnn-score-"
        ) as staging_directory:
            provider = provider_for_environment(
                self._environment,
                staging_directory=staging_directory,
            )
            request = prepare_scoring_request(
                provider=provider,
                structure=structure,
                sequence=sequence,
            )
            with self._run_resources.engine_invocation(
                engine_role="score_subject",
                engine_identity=(
                    "proteinmpnn.score.local."
                    "proteinmpnn.score.v_48_020_8907e667"
                ),
            ):
                raw_score = provider.score(request, sequence)
            score = validate_scoring_result(raw_score)
        observation = ScoreObservation(
            candidate_id=sequence_candidate.candidate_id,
            metric=self._contract_reference(
                "metric",
                "proteinmpnn.native_sequence_nll",
            ),
            method=self._contract_reference(
                "method",
                "proteinmpnn.score.v_48_020_8907e667",
            ),
            context=IntrinsicObservationContext(),
            value=score,
        )
        return {
            "scores": ScoreCollection(
                "proteinmpnn-score-observations",
                [observation],
            )
        }
