"""The single production registration for shared protein folding."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from core import (
    AvailabilityDeclaration,
    AvailabilityResult,
    BehaviorReference,
    ContractIdentity,
    DefinitionResource,
    EffectiveRandomnessResolver,
    ExecutionBindingDefinition,
    LazyImplementationFactory,
    MethodDefinition,
    ModulePackageRegistration,
    ProducedObservationDefinition,
    ReadinessDeclaration,
)
from core.provider_contract import validate_installed_provider_checkout

from .adapter import (
    ESM_SDK_REVISION,
    LOCAL_DEVICE,
    LOCAL_ESMC_ARTIFACT_SHA256,
    LOCAL_ESMC_MODEL,
    LOCAL_ESMC_REVISION,
    LOCAL_ESMFOLD2_ARTIFACT_SHA256,
    LOCAL_ESMFOLD2_MODEL,
    LOCAL_ESMFOLD2_REVISION,
    LOCAL_TORCH_VERSION,
    REMOTE_ESMFOLD2_MODEL,
    TRANSFORMERS_REVISION,
    local_readiness,
    local_runtime_structurally_available,
    remote_readiness,
    remote_runtime_structurally_available,
)


_VERSION = "2.0.0"
_METRICS = (
    "structure.ptm",
    "structure.plddt.per_residue",
    "structure.plddt.mean_residue",
)


def _remote_available() -> AvailabilityResult:
    if not remote_runtime_structurally_available():
        return AvailabilityResult.unavailable(
            code="remote_esmfold2_runtime_unavailable",
            message="The exact remote ESMFold2 SDK runtime is unavailable.",
            retryable=False,
        )
    try:
        validate_installed_provider_checkout("esm", ESM_SDK_REVISION)
    except (OSError, RuntimeError, ValueError):
        return AvailabilityResult.unavailable(
            code="remote_esmfold2_runtime_unavailable",
            message="The exact remote ESMFold2 SDK runtime is unavailable.",
            retryable=False,
        )
    return AvailabilityResult.available()


def _local_available() -> AvailabilityResult:
    if local_runtime_structurally_available():
        return AvailabilityResult.available()
    return AvailabilityResult.unavailable(
        code="local_esmfold2_runtime_unavailable",
        message="The exact local ESMFold2 runtime is unavailable.",
        retryable=False,
    )


def _resolve_effective_randomness(
    *,
    inputs: Mapping[str, Any],
    node_parameters: Mapping[str, Any],
    binding_parameters: Mapping[str, Any],
) -> dict[str, Any]:
    del inputs
    if binding_parameters:
        raise ValueError("folding Bindings accept no route parameters")
    seed = node_parameters.get("effective_seed")
    if (
        type(seed) is not int
        or seed < 0
        or seed > 9_007_199_254_740_991
    ):
        raise ValueError("effective_seed must be one resolved I-JSON integer")
    return {"effective_seed": seed}


def _build(route: str, method_id: str):
    def factory(**kwargs: object) -> object:
        from .implementation import ESMFold2FoldingImplementation

        return ESMFold2FoldingImplementation(
            kwargs["run_resources"],
            kwargs["environment_configuration"],
            kwargs["frozen_catalog"],
            route=route,
            method_id=method_id,
        )

    return factory


def _method(route: str) -> MethodDefinition:
    if route == "remote":
        return MethodDefinition(
            method_id="folding.fold.esmfold2_fast_biohub_2026_05",
            version=_VERSION,
            algorithm_identity={
                "name": "ESMFold2 sequence-to-structure diffusion",
                "num_loops": 20,
                "num_sampling_steps": 100,
                "lm_dropout": 0.3,
                "lm_mask_pct": 0.1,
                "msa_max_depth": 1024,
                "msa_column_mask_rate": 0.1,
                "include_pae": True,
            },
            model_identity={
                "model": REMOTE_ESMFOLD2_MODEL,
                "source": "Biohub",
                "release": "2026-05",
            },
            checkpoint_identity={
                "kind": "provider_managed_exact_model_id",
                "model": REMOTE_ESMFOLD2_MODEL,
            },
            featurization_identity={
                "input": "single-chain canonical protein sequence",
                "output": "provider atom37 PDB",
            },
            source_identity={
                "sdk": "esm",
                "sdk_source_revision": ESM_SDK_REVISION,
                "service": "Biohub",
            },
            scale_contract={
                "ptm": "provider_native_[0,1]",
                "plddt": "provider_native_[0,1]_multiply_100",
                "pae": "provider_native_angstrom",
            },
        )
    return MethodDefinition(
        method_id="folding.fold.esmfold2_hf_1ebf0e3",
        version=_VERSION,
        algorithm_identity={
            "name": "ESMFold2 sequence-to-structure diffusion",
            "num_loops": 20,
            "num_sampling_steps": 100,
            "lm_dropout": 0.3,
            "lm_mask_pct": 0.1,
            "msa_max_depth": 1024,
            "msa_column_mask_rate": 0.1,
            "include_pae": True,
        },
        model_identity={
            "model": LOCAL_ESMFOLD2_MODEL,
            "source": "Hugging Face",
            "snapshot_revision": LOCAL_ESMFOLD2_REVISION,
            "language_model": LOCAL_ESMC_MODEL,
            "language_model_snapshot_revision": LOCAL_ESMC_REVISION,
        },
        checkpoint_identity={
            "kind": "immutable_huggingface_snapshots",
            "esmfold2_artifact_sha256": dict(
                sorted(LOCAL_ESMFOLD2_ARTIFACT_SHA256.items())
            ),
            "esmc_artifact_sha256": dict(
                sorted(LOCAL_ESMC_ARTIFACT_SHA256.items())
            ),
        },
        featurization_identity={
            "input": "ESMFold2 StructurePredictionInput single protein",
            "output": "MolecularComplex protein-only PDB",
        },
        source_identity={
            "sdk": "esm",
            "sdk_source_revision": ESM_SDK_REVISION,
            "transformers_source_revision": TRANSFORMERS_REVISION,
            "service": "local_huggingface",
        },
        scale_contract={
            "ptm": "provider_native_[0,1]",
            "plddt": "provider_native_[0,1]_multiply_100",
            "pae": "provider_native_angstrom",
        },
    )


def _produced_observations() -> tuple[ProducedObservationDefinition, ...]:
    observations = [
        ProducedObservationDefinition(
            output_port="confidence_observations",
            metric=ContractIdentity("metric", metric, _VERSION),
            context_profile={"kind": "intrinsic"},
            subject_grain="candidate",
            source_role="subject",
            subject_direction="output",
            subject_port="structure_candidates",
            guaranteed_multiplicity="one",
            output_partition="folding_confidence",
        )
        for metric in _METRICS
    ]
    observations.append(
        ProducedObservationDefinition(
            output_port="pae_observations",
            metric=ContractIdentity(
                "metric",
                "structure.pae",
                _VERSION,
            ),
            context_profile={"kind": "intrinsic"},
            subject_grain="candidate",
            source_role="subject",
            subject_direction="output",
            subject_port="structure_candidates",
            guaranteed_multiplicity="one",
            output_partition="folding_confidence",
        )
    )
    return tuple(observations)


def _binding(route: str) -> ExecutionBindingDefinition:
    if route == "remote":
        binding_id = "folding.fold.esmfold2_remote"
        method_id = "folding.fold.esmfold2_fast_biohub_2026_05"
        model = REMOTE_ESMFOLD2_MODEL
        availability = AvailabilityDeclaration(
            behavior=BehaviorReference(
                "folding.esmfold2_remote/availability",
                _VERSION,
                {"observation": "startup"},
            ),
            prerequisites={
                "provider_sdk": {
                    "name": "esm",
                    "source_revision": ESM_SDK_REVISION,
                },
            },
            check=_remote_available,
        )
        readiness = ReadinessDeclaration(
            behavior=BehaviorReference(
                "folding.esmfold2_remote/readiness",
                _VERSION,
                {
                    "observation": "per-run",
                    "cache_order": "before-cache-lookup",
                    "secret_retention": "none",
                },
            ),
            prerequisites={
                "credential": {
                    "source": "trusted_environment_configuration",
                },
                "endpoint": {
                    "endpoint_id": "biohub",
                    "source": "trusted_environment_configuration",
                },
                "provider_sdk": {
                    "name": "esm",
                    "source_revision": ESM_SDK_REVISION,
                },
            },
            check=remote_readiness,
        )
        implementation_identity = {
            "name": "folding.esmfold2.remote-adapter",
            "route": "Biohub",
            "model": model,
            "sdk_source_revision": ESM_SDK_REVISION,
            "seed_control": "unsupported_by_provider",
            "cache_policy": "uncontrolled_remote_folding_not_cacheable",
        }
        adapter_details = {
            "provider_contract": "esm-sdk-fold@917af90b",
            "native_scale": "[0,1]_multiply_100",
        }
        seed_control = "unsupported_by_provider"
    else:
        binding_id = "folding.fold.esmfold2_local"
        method_id = "folding.fold.esmfold2_hf_1ebf0e3"
        model = LOCAL_ESMFOLD2_MODEL
        availability = AvailabilityDeclaration(
            behavior=BehaviorReference(
                "folding.esmfold2_local/availability",
                _VERSION,
                {"observation": "startup", "model_load": "forbidden"},
            ),
            prerequisites={
                "provider_sdk": {
                    "name": "esm",
                    "source_revision": ESM_SDK_REVISION,
                },
                "transformers": {
                    "source_revision": TRANSFORMERS_REVISION,
                },
                "torch": {"version": LOCAL_TORCH_VERSION},
            },
            check=_local_available,
        )
        readiness = ReadinessDeclaration(
            behavior=BehaviorReference(
                "folding.esmfold2_local/readiness",
                _VERSION,
                {
                    "observation": "per-run",
                    "cache_order": "before-cache-lookup",
                    "secret_retention": "none",
                },
            ),
            prerequisites={
                "model_snapshot": {
                    "source": LOCAL_ESMFOLD2_MODEL,
                    "snapshot_revision": LOCAL_ESMFOLD2_REVISION,
                    "artifact_sha256": dict(
                        sorted(LOCAL_ESMFOLD2_ARTIFACT_SHA256.items())
                    ),
                    "path_source": "trusted_environment_configuration",
                },
                "language_model_snapshot": {
                    "source": LOCAL_ESMC_MODEL,
                    "snapshot_revision": LOCAL_ESMC_REVISION,
                    "artifact_sha256": dict(
                        sorted(LOCAL_ESMC_ARTIFACT_SHA256.items())
                    ),
                    "path_source": "trusted_environment_configuration",
                },
                "device": {
                    "source": "trusted_environment_configuration",
                    "exact_value": LOCAL_DEVICE,
                },
                "runtime_directory": {
                    "source": "trusted_environment_configuration",
                },
                "runtime_fingerprint": {
                    "source": "trusted_environment_configuration",
                    "safe_public_identity": True,
                },
            },
            check=local_readiness,
        )
        implementation_identity = {
            "name": "folding.esmfold2.local-adapter",
            "route": "local_huggingface",
            "model": model,
            "model_snapshot_revision": LOCAL_ESMFOLD2_REVISION,
            "language_model": LOCAL_ESMC_MODEL,
            "language_model_snapshot_revision": LOCAL_ESMC_REVISION,
            "device": LOCAL_DEVICE,
            "torch_version": LOCAL_TORCH_VERSION,
            "transformers_source_revision": TRANSFORMERS_REVISION,
            "seed_control": "torch_local",
            "cache_policy": "runtime-device-specific_folding_not_cacheable",
        }
        adapter_details = {
            "provider_contract": "esmfold2-huggingface-local@1ebf0e3",
            "native_scale": "[0,1]_multiply_100",
        }
        seed_control = "torch_local"
    return ExecutionBindingDefinition(
        binding_id=binding_id,
        version=_VERSION,
        node_type=ContractIdentity(
            "node_type",
            "folding.fold",
            _VERSION,
        ),
        method=ContractIdentity("method", method_id, _VERSION),
        binding_parameters={},
        execution_route="adapter",
        factory=LazyImplementationFactory(
            behavior=BehaviorReference(
                "folding.fold/factory",
                _VERSION,
                {"route": route, "model": model},
            ),
            build=_build(route, method_id),
        ),
        adapter_behavior=BehaviorReference(
            f"folding.esmfold2_{route}/adapter",
            _VERSION,
            adapter_details,
        ),
        availability=availability,
        readiness=readiness,
        deterministic=False,
        cacheable=False,
        implementation_identity=implementation_identity,
        produced_observations=_produced_observations(),
        effective_randomness_parameters=("effective_seed",),
        effective_randomness_resolver=EffectiveRandomnessResolver(
            behavior=BehaviorReference(
                f"folding.esmfold2_{route}/effective-randomness",
                _VERSION,
                {
                    "provider_seed_control": seed_control,
                    "sample_order": "parent-then-zero-based-sample",
                },
            ),
            resolve=_resolve_effective_randomness,
        ),
    )


MODULE_PACKAGE = ModulePackageRegistration(
    schema_version=_VERSION,
    package_id="folding",
    package_version=_VERSION,
    package_module=__package__,
    node_definitions=(DefinitionResource("definitions/fold.yaml"),),
    metric_definitions=(
        DefinitionResource("definitions/plddt_per_residue_metric.yaml"),
        DefinitionResource("definitions/plddt_mean_residue_metric.yaml"),
        DefinitionResource("definitions/ptm_metric.yaml"),
        DefinitionResource("definitions/pae_metric.yaml"),
    ),
    methods=(_method("remote"), _method("local")),
    bindings=(_binding("remote"), _binding("local")),
)
