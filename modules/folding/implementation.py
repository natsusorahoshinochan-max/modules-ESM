"""One folding implementation shared by explicit remote and local Bindings."""

from __future__ import annotations

from collections.abc import Mapping
import hashlib
from typing import Any

from core.provider_contract import esm_provider_identity
from core.provider_evidence import record_provider_call_result
from core.run_context import RunContext
from datatypes import (
    Candidate,
    CandidateCollection,
    ExactContractReference,
    IntrinsicObservationContext,
    ProteinSequence,
    ScoreCollection,
    ScoreObservation,
)

from .adapter import (
    ESM_SDK_REVISION,
    LOCAL_ESMC_ARTIFACT_SHA256,
    LOCAL_ESMC_REVISION,
    LOCAL_ESMFOLD2_ARTIFACT_SHA256,
    LOCAL_ESMFOLD2_MODEL,
    LOCAL_ESMFOLD2_REVISION,
    REMOTE_ESMFOLD2_MODEL,
    decode_local_fold_result,
    decode_remote_fold_result,
    fixed_folding_config,
    load_local_engine,
    remote_client,
    resolve_local_runtime,
)


class ESMFold2FoldingImplementation:
    """Fold sequence Candidates through exactly one selected Binding."""

    def __init__(
        self,
        run_resources: Any,
        environment: Mapping[str, Any],
        catalog: Any,
        *,
        route: str,
        method_id: str,
    ) -> None:
        if route not in {"remote", "local"}:
            raise ValueError("ESMFold2 route is not declared")
        self._run_resources = run_resources
        self._environment = environment
        self._catalog = catalog
        self._route = route
        self._method_id = method_id

    @staticmethod
    def _parameters(parameters: Mapping[str, Any]) -> tuple[int, int]:
        if set(parameters) != {"effective_seed", "num_samples"}:
            raise ValueError("folding parameters are not fully resolved")
        seed = parameters["effective_seed"]
        count = parameters["num_samples"]
        if (
            type(seed) is not int
            or seed < 0
            or seed > 9_007_199_254_740_991
            or type(count) is not int
            or count < 1
            or count > 100
        ):
            raise ValueError("folding parameters are outside their contract")
        return seed, count

    @staticmethod
    def _inputs(inputs: Mapping[str, Any]) -> list[Candidate]:
        if set(inputs) != {"sequence_candidates"}:
            raise ValueError(
                "folding requires one sequence Candidate Collection"
            )
        collection = inputs["sequence_candidates"]
        if (
            type(collection) is not CandidateCollection
            or collection.item_type != "protein.sequence"
            or not collection.items
        ):
            raise ValueError(
                "folding requires non-empty protein sequence Candidates"
            )
        for candidate in collection.items:
            if type(candidate) is not Candidate or type(
                candidate.data
            ) is not ProteinSequence:
                raise ValueError("folding received an incomplete sequence")
        return list(collection.items)

    @staticmethod
    def _call_seed(
        effective_seed: int,
        parent_index: int,
        sample_index: int,
    ) -> int:
        digest = hashlib.sha256(
            (
                "protein-workbench-esmfold2-call/v2\0"
                f"{effective_seed}\0{parent_index}\0{sample_index}"
            ).encode()
        ).digest()
        return int.from_bytes(digest[:7], "big") % 9_007_199_254_740_992

    def _contract_reference(
        self,
        kind: str,
        contract_id: str,
    ) -> ExactContractReference:
        contract = self._catalog.require_contract(
            kind,
            contract_id,
            "2.0.0",
        )
        return ExactContractReference(**contract.reference())

    def _provider_identity(self) -> dict[str, Any]:
        if self._route == "remote":
            return esm_provider_identity()
        return {
            "sdk": "esm",
            "sdk_source_revision": ESM_SDK_REVISION,
            "service": "local_esmfold2",
            "source": LOCAL_ESMFOLD2_MODEL,
            "source_revision": LOCAL_ESMFOLD2_REVISION,
            "snapshot_revision": LOCAL_ESMC_REVISION,
            "artifact_sha256": {
                "esmfold2": dict(
                    sorted(LOCAL_ESMFOLD2_ARTIFACT_SHA256.items())
                ),
                "esmc": dict(sorted(LOCAL_ESMC_ARTIFACT_SHA256.items())),
            },
        }

    def _record_provider_result(
        self,
        *,
        sequence: ProteinSequence,
        pdb_string: str,
        effective_seed: int | None,
    ) -> None:
        record_provider_call_result(
            provider=(
                "biohub"
                if self._route == "remote"
                else "local-esmfold2"
            ),
            operation="esmfold2.fold",
            model=(
                REMOTE_ESMFOLD2_MODEL
                if self._route == "remote"
                else LOCAL_ESMFOLD2_MODEL
            ),
            provider_identity=self._provider_identity(),
            effective_seed=effective_seed,
            seed_control=(
                "unsupported_by_provider"
                if self._route == "remote"
                else "torch_local"
            ),
            result_summary={
                "input_sequence_length": len(sequence.sequence),
                "input_sequence_sha256": hashlib.sha256(
                    sequence.sequence.encode()
                ).hexdigest(),
                "pdb_bytes": len(pdb_string.encode()),
                "pdb_sha256": hashlib.sha256(
                    pdb_string.encode()
                ).hexdigest(),
                "score_ids": [
                    "structure.pae",
                    "structure.plddt.mean_residue",
                    "structure.plddt.per_residue",
                    "structure.ptm",
                ],
            },
        )

    def execute(
        self,
        *,
        inputs: Mapping[str, Any],
        node_parameters: Mapping[str, Any],
        binding_parameters: Mapping[str, Any],
    ) -> dict[str, Any]:
        if binding_parameters:
            raise ValueError("folding Bindings accept no route parameters")
        parents = self._inputs(inputs)
        effective_seed, sample_count = self._parameters(node_parameters)
        if self._route == "remote":
            engine = remote_client(self._environment)
            runtime_fingerprint = None
        else:
            runtime = resolve_local_runtime(self._environment)
            engine = load_local_engine(self._environment, runtime)
            runtime_fingerprint = runtime.safe_fingerprint

        method = self._contract_reference("method", self._method_id)
        metrics = {
            metric_id: self._contract_reference("metric", metric_id)
            for metric_id in (
                "structure.ptm",
                "structure.plddt.per_residue",
                "structure.plddt.mean_residue",
                "structure.pae",
            )
        }
        candidates: list[Candidate] = []
        confidence: list[ScoreObservation] = []
        pae: list[ScoreObservation] = []
        for parent_index, parent in enumerate(parents):
            sequence = parent.data
            assert type(sequence) is ProteinSequence
            for sample_index in range(sample_count):
                call_seed = self._call_seed(
                    effective_seed,
                    parent_index,
                    sample_index,
                )
                provider = (
                    "biohub"
                    if self._route == "remote"
                    else "local-esmfold2"
                )
                model = (
                    REMOTE_ESMFOLD2_MODEL
                    if self._route == "remote"
                    else LOCAL_ESMFOLD2_MODEL
                )
                RunContext.record_active_provider_call(
                    provider,
                    "esmfold2.fold",
                    model=model,
                )
                with self._run_resources.engine_invocation(
                    engine_role=f"fold_parent_{parent_index}_sample_{sample_index}",
                    engine_identity=(
                        f"folding.esmfold2_{self._route}."
                        f"{self._method_id}"
                    ),
                ):
                    if self._route == "remote":
                        raw = engine.fold(
                            sequence=sequence.sequence,
                            model_name=REMOTE_ESMFOLD2_MODEL,
                            config=fixed_folding_config(),
                        )
                    else:
                        raw = engine.fold(
                            sequence=sequence.sequence,
                            effective_seed=call_seed,
                        )
                    decoded = (
                        decode_remote_fold_result(raw, sequence)
                        if self._route == "remote"
                        else decode_local_fold_result(raw, sequence)
                    )
                self._record_provider_result(
                    sequence=sequence,
                    pdb_string=decoded.structure.pdb_string,
                    effective_seed=(
                        None if self._route == "remote" else call_seed
                    ),
                )
                raw_candidate_id = (
                    f"fold-{parent_index}-sample-{sample_index}"
                )
                candidate = Candidate(
                    raw_candidate_id,
                    decoded.structure,
                    [parent.candidate_id],
                    {
                        "route": self._route,
                        "model": model,
                        "parent_index": parent_index,
                        "sample_index": sample_index,
                        "effective_seed": effective_seed,
                        "effective_call_seed": call_seed,
                        "seed_control": (
                            "unsupported_by_provider"
                            if self._route == "remote"
                            else "torch_local"
                        ),
                        "runtime_fingerprint": runtime_fingerprint,
                    },
                )
                candidates.append(candidate)
                values = (
                    ("structure.ptm", decoded.confidence.ptm),
                    (
                        "structure.plddt.per_residue",
                        list(decoded.confidence.per_residue_plddt),
                    ),
                    (
                        "structure.plddt.mean_residue",
                        decoded.confidence.mean_residue_plddt,
                    ),
                )
                for metric_id, value in values:
                    confidence.append(
                        ScoreObservation(
                            candidate_id=raw_candidate_id,
                            metric=metrics[metric_id],
                            method=method,
                            context=IntrinsicObservationContext(),
                            value=value,
                            source_partition="folding_confidence",
                        )
                    )
                pae.append(
                    ScoreObservation(
                        candidate_id=raw_candidate_id,
                        metric=metrics["structure.pae"],
                        method=method,
                        context=IntrinsicObservationContext(),
                        value=[
                            list(row)
                            for row in decoded.confidence.pae
                        ],
                        source_partition="folding_confidence",
                    )
                )
        return {
            "structure_candidates": CandidateCollection(
                "folding-structure-candidates",
                "protein.structure",
                candidates,
            ),
            "confidence_observations": ScoreCollection(
                "folding-confidence",
                confidence,
            ),
            "pae_observations": ScoreCollection(
                "folding-pae",
                pae,
            ),
        }
