"""v2 ProteinMPNN constraint and sequence-design implementations."""

from __future__ import annotations

from collections.abc import Mapping
import hashlib
import math
from typing import Any

from core.run_context import RunContext
from datatypes import (
    Candidate,
    CandidateCollection,
    ProteinMPNNConstraints,
    ProteinSequence,
    ProteinStructure,
)

from .domain import author_constraints, random_fixed_positions
from .v2_adapter import (
    PROTEINMPNN_MODEL,
    prepare_design_request,
    provider_for_environment,
    record_design_result,
    validate_design_result,
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
                "proteinmpnn.constraints.repository_owned/2.0.0"
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
                "repository_owned/2.0.0"
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
    def _parents(inputs: Mapping[str, Any], node_id: str) -> list[Candidate]:
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
            return [
                Candidate(
                    node_id,
                    structure,
                    [],
                    {"input_mode": "standalone"},
                )
            ]
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
        parents: list[Candidate] = []
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
            parents.append(candidate)
        return parents

    @staticmethod
    def _parameters(
        node_parameters: Mapping[str, Any],
        binding_parameters: Mapping[str, Any],
    ) -> tuple[int, int, float, float]:
        if binding_parameters or set(node_parameters) != {
            "effective_seed",
            "num_sequences",
            "temperature",
            "backbone_noise",
        }:
            raise ValueError(
                "ProteinMPNN design parameters are not fully resolved"
            )
        seed = node_parameters["effective_seed"]
        count = node_parameters["num_sequences"]
        temperature = node_parameters["temperature"]
        noise = node_parameters["backbone_noise"]
        if (
            type(seed) is not int
            or not 0 <= seed <= 9_007_199_254_740_991
            or type(count) is not int
            or not 1 <= count <= 100
            or isinstance(temperature, bool)
            or not isinstance(temperature, (int, float))
            or not math.isfinite(float(temperature))
            or not 0 < float(temperature) <= 10
            or isinstance(noise, bool)
            or not isinstance(noise, (int, float))
            or not math.isfinite(float(noise))
            or not 0 <= float(noise) <= 10
        ):
            raise ValueError(
                "ProteinMPNN design parameters are outside their contract"
            )
        return seed, count, float(temperature), float(noise)

    @staticmethod
    def _call_seed(
        effective_seed: int,
        parent: Candidate,
    ) -> int:
        structure = parent.data
        assert type(structure) is ProteinStructure
        digest = hashlib.sha256(
            (
                "protein-workbench-proteinmpnn-parent-seed/v2\0"
                f"{effective_seed}\0"
                f"{parent.candidate_id}\0"
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
            "2.0.0",
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
        effective_constraints = constraints or ProteinMPNNConstraints()
        constraint_digest = self._constraint_digest(effective_constraints)
        candidates: list[Candidate] = []
        for parent_index, parent in enumerate(parents):
            structure = parent.data
            assert type(structure) is ProteinStructure
            call_seed = self._call_seed(seed, parent)
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
                RunContext.record_active_provider_call(
                    provider.provider_identity,
                    "design_sequences",
                    model=PROTEINMPNN_MODEL,
                    details={
                        "parent_candidate_id": parent.candidate_id,
                        "candidate_ids": raw_ids,
                        "effective_seed": call_seed,
                    },
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
                record_design_result(
                    provider=provider,
                    structure=structure,
                    sequences=sequences,
                    scores=scores,
                    effective_seed=call_seed,
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
                        },
                    )
                )
        if len(candidates) != len(parents) * count:
            raise RuntimeError("ProteinMPNN design children are incomplete")
        for parent in parents:
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
