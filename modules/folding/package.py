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
    ModulePackageRegistration,
    OperationContext,
    ProducedObservationDefinition,
    ReadinessCheckInput,
    ReadinessDeclaration,
    ReadinessResult,
    ScientificOperation,
    ScientificOperationFactory,
)
from modules.provider_contract import validate_installed_provider_checkout
from modules.provider_contract import (
    SIMPLEFOLD_ARTIFACT_SHA256,
    SIMPLEFOLD_ESM2_ARTIFACT_SHA256,
    SIMPLEFOLD_ESM2_REVISION,
    SIMPLEFOLD_ESM2_SOURCE_TREE_SHA256,
    SIMPLEFOLD_REVISION,
)

from .contracts import (
    CONFIDENCE_METHOD_VERSION,
    FOLD_METHOD_VERSION,
    LOCAL_ESMFOLD2_METHOD_VERSION,
    LOCAL_ESMFOLD2_FOLD_METHOD,
    REMOTE_ESMFOLD2_FOLD_METHOD,
    SIMPLEFOLD_CONFIDENCE_METHOD,
    SIMPLEFOLD_FOLD_METHOD,
)

from .adapter import (
    BiohubESMFold2Adapter,
    ESM_SDK_REVISION,
    LOCAL_DEVICE,
    LOCAL_ESMC_ARTIFACT_SHA256,
    LOCAL_ESMC_MODEL,
    LOCAL_ESMC_REVISION,
    LOCAL_ESMFOLD2_ARTIFACT_SHA256,
    LOCAL_ESMFOLD2_MODEL,
    LOCAL_ESMFOLD2_REVISION,
    LOCAL_TORCH_VERSION,
    LocalESMFold2Adapter,
    REMOTE_ESMFOLD2_MODEL,
    TRANSFORMERS_REVISION,
    local_readiness,
    local_runtime_structurally_available,
    remote_readiness,
    remote_runtime_structurally_available,
)
from .simplefold_adapter import (
    LocalSimpleFoldAdapter,
    SIMPLEFOLD_DEVICE,
    SIMPLEFOLD_MODEL,
    simplefold_readiness,
    simplefold_runtime_structurally_available,
)
from .simplefold_confidence_adapter import (
    LocalSimpleFoldConfidenceAdapter,
    SIMPLEFOLD_CONFIDENCE_ADAPTER,
    SIMPLEFOLD_CONFIDENCE_DEVICE,
    SIMPLEFOLD_CONFIDENCE_FEATURIZATION,
    configured_runtime_fingerprint as confidence_runtime_fingerprint,
    simplefold_confidence_readiness,
    simplefold_confidence_runtime_structurally_available,
)
from .simplefold_contract import (
    simplefold_confidence_artifact_sha256,
    simplefold_confidence_esm2_artifact_sha256,
    simplefold_folding_artifact_sha256,
)


_PACKAGE_VERSION = "6.0.0"
_FOLD_NODE_BINDING_VERSION = "6.0.0"
_REMOTE_FOLD_BINDING_VERSION = "7.0.0"
_LOCAL_ESMFOLD2_BINDING_VERSION = "7.0.0"
_CONFIDENCE_NODE_BINDING_VERSION = "4.0.0"
_METRIC_VERSIONS = {
    "structure.ptm": "2.1.0",
    "structure.plddt.per_residue": "3.0.0",
    "structure.plddt.mean_residue": "3.0.0",
    "structure.pae": "3.0.0",
}


def _remote_ready(check_input: ReadinessCheckInput) -> ReadinessResult:
    return ReadinessResult(remote_readiness(check_input.values))


def _local_ready(check_input: ReadinessCheckInput) -> ReadinessResult:
    return local_readiness(check_input.values)


def _simplefold_ready(
    check_input: ReadinessCheckInput,
) -> ReadinessResult:
    return simplefold_readiness(check_input.values)


def _simplefold_confidence_ready(
    check_input: ReadinessCheckInput,
) -> ReadinessResult:
    return simplefold_confidence_readiness(check_input.values)


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


def _simplefold_available() -> AvailabilityResult:
    if simplefold_runtime_structurally_available():
        return AvailabilityResult.available()
    return AvailabilityResult.unavailable(
        code="simplefold_runtime_unavailable",
        message="The exact local SimpleFold runtime is unavailable.",
        retryable=False,
    )


def _simplefold_confidence_available() -> AvailabilityResult:
    if simplefold_confidence_runtime_structurally_available():
        return AvailabilityResult.available()
    return AvailabilityResult.unavailable(
        code="simplefold_confidence_runtime_unavailable",
        message=(
            "The exact local SimpleFold confidence runtime is unavailable."
        ),
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


def _resolve_simplefold_effective_randomness(
    *,
    inputs: Mapping[str, Any],
    node_parameters: Mapping[str, Any],
    binding_parameters: Mapping[str, Any],
) -> dict[str, Any]:
    del inputs
    if set(binding_parameters) != {"num_steps"}:
        raise ValueError("SimpleFold Binding parameters are not resolved")
    seed = node_parameters.get("effective_seed")
    if (
        type(seed) is not int
        or seed < 0
        or seed > 9_007_199_254_740_991
    ):
        raise ValueError("effective_seed must be one resolved I-JSON integer")
    return {"effective_seed": seed}


def _build_remote(context: OperationContext) -> ScientificOperation:
    from .implementation import ESMFold2FoldingImplementation

    return ESMFold2FoldingImplementation(
        adapter=BiohubESMFold2Adapter(
            environment=context.environment,
            resources=context.resources,
        ),
        method=context.method,
    )


def _build_local(context: OperationContext) -> ScientificOperation:
    from .implementation import ESMFold2FoldingImplementation

    return ESMFold2FoldingImplementation(
        adapter=LocalESMFold2Adapter(
            environment=context.environment,
            resources=context.resources,
        ),
        method=context.method,
    )


def _build_simplefold(context: OperationContext) -> ScientificOperation:
    from .implementation import SimpleFoldFoldingImplementation

    return SimpleFoldFoldingImplementation(
        adapter=LocalSimpleFoldAdapter(
            environment=context.environment,
            resources=context.resources,
        ),
        method=context.method,
    )


def _build_simplefold_confidence(
    context: OperationContext,
) -> ScientificOperation:
    from .implementation import SimpleFoldConfidenceImplementation

    return SimpleFoldConfidenceImplementation(
        adapter=LocalSimpleFoldConfidenceAdapter(
            environment=context.environment,
            resources=context.resources,
        ),
        method=context.method,
        produced_observations=context.produced_observations,
    )


def _binding(route: str) -> ExecutionBindingDefinition:
    if route == "remote":
        binding_version = _REMOTE_FOLD_BINDING_VERSION
        binding_id = "folding.fold.esmfold2_remote"
        method_id = "folding.fold.esmfold2_fast_biohub_2026_05"
        model = REMOTE_ESMFOLD2_MODEL
        availability = AvailabilityDeclaration(
            behavior=BehaviorReference(
                "folding.esmfold2_remote/availability",
                binding_version,
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
                binding_version,
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
            check=_remote_ready,
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
            "engine_identity": "exact_method_contract_digest",
            "randomness_evidence": "provider_uncontrolled",
        }
    else:
        binding_version = _LOCAL_ESMFOLD2_BINDING_VERSION
        binding_id = "folding.fold.esmfold2_local"
        method_id = "folding.fold.esmfold2_hf_1ebf0e3"
        model = LOCAL_ESMFOLD2_MODEL
        availability = AvailabilityDeclaration(
            behavior=BehaviorReference(
                "folding.esmfold2_local/availability",
                binding_version,
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
                binding_version,
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
            check=_local_ready,
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
            "seed_control": "python_numpy_mt19937_torch_shared",
            "cache_policy": "runtime-device-specific_folding_not_cacheable",
        }
        adapter_details = {
            "provider_contract": "esmfold2-huggingface-local@1ebf0e3",
            "native_scale": "[0,1]_multiply_100",
            "engine_identity": "exact_method_contract_digest",
            "randomness_evidence": "exact_seed",
            "provider_seed_domain": "unsigned_32_bit",
        }
        seed_control = "python_numpy_mt19937_torch_shared"
        seed_scope = "scientific-input-content-and-parent-sample-slot"
    return ExecutionBindingDefinition(
        binding_id=binding_id,
        version=binding_version,
        node_type=ContractIdentity(
            "node_type",
            "folding.fold",
            _FOLD_NODE_BINDING_VERSION,
        ),
        method=ContractIdentity(
            "method",
            method_id,
            (
                FOLD_METHOD_VERSION
                if route == "remote"
                else LOCAL_ESMFOLD2_METHOD_VERSION
            ),
        ),
        binding_parameters={},
        execution_route="adapter",
        factory=ScientificOperationFactory(
            behavior=BehaviorReference(
                "folding.fold/factory",
                binding_version,
                {"route": route, "model": model},
            ),
            build=_build_remote if route == "remote" else _build_local,
        ),
        adapter_behavior=BehaviorReference(
            f"folding.esmfold2_{route}/adapter",
            binding_version,
            adapter_details,
        ),
        availability=availability,
        readiness=readiness,
        deterministic=False,
        cacheable=False,
        implementation_identity=implementation_identity,
        effective_randomness_parameters=(
            () if route == "remote" else ("effective_seed",)
        ),
        effective_randomness_resolver=(
            None
            if route == "remote"
            else EffectiveRandomnessResolver(
                behavior=BehaviorReference(
                    f"folding.esmfold2_{route}/effective-randomness",
                    binding_version,
                    {
                        "provider_seed_control": seed_control,
                        "provider_seed_domain": "unsigned_32_bit",
                        "seed_scope": seed_scope,
                        "sample_order": "parent-then-zero-based-sample",
                    },
                ),
                resolve=_resolve_effective_randomness,
            )
        ),
    )


def _simplefold_binding() -> ExecutionBindingDefinition:
    method_id = "folding.fold.simplefold_100m_c7a5570"
    return ExecutionBindingDefinition(
        binding_id="folding.fold.simplefold_local",
        version=_FOLD_NODE_BINDING_VERSION,
        node_type=ContractIdentity(
            "node_type",
            "folding.fold",
            _FOLD_NODE_BINDING_VERSION,
        ),
        method=ContractIdentity("method", method_id, FOLD_METHOD_VERSION),
        binding_parameters={
            "num_steps": {
                "parameter_scope": "scientific",
                "scientific_meaning": (
                    "Exact SimpleFold Euler-Maruyama sampling step count."
                ),
                "value_contract": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 50,
                },
                "default": 50,
            },
        },
        execution_route="adapter",
        factory=ScientificOperationFactory(
            behavior=BehaviorReference(
                "folding.fold/factory",
                _FOLD_NODE_BINDING_VERSION,
                {"route": "simplefold_local", "model": SIMPLEFOLD_MODEL},
            ),
            build=_build_simplefold,
        ),
        adapter_behavior=BehaviorReference(
            "folding.simplefold_local/adapter",
            _FOLD_NODE_BINDING_VERSION,
            {
                "provider_contract": (
                    f"ml-simplefold@{SIMPLEFOLD_REVISION}"
                ),
                "native_scale": "[0,100]_identity",
                "staging": "one-private-directory-per-engine-invocation",
                "engine_identity": "exact_method_contract_digest",
                "randomness_evidence": "exact_seed",
            },
        ),
        availability=AvailabilityDeclaration(
            behavior=BehaviorReference(
                "folding.simplefold_local/availability",
                _FOLD_NODE_BINDING_VERSION,
                {"observation": "startup", "model_load": "forbidden"},
            ),
            prerequisites={
                "provider": {
                    "name": "simplefold",
                    "source_revision": SIMPLEFOLD_REVISION,
                },
                "runtime": {"name": "torch"},
            },
            check=_simplefold_available,
        ),
        readiness=ReadinessDeclaration(
            behavior=BehaviorReference(
                "folding.simplefold_local/readiness",
                _FOLD_NODE_BINDING_VERSION,
                {
                    "observation": "per-run",
                    "cache_order": "before-cache-lookup",
                    "model_load": "forbidden",
                },
            ),
            prerequisites={
                "simplefold_models": {
                    "artifact_sha256": (
                        simplefold_folding_artifact_sha256()
                    ),
                    "path_source": "trusted_environment_configuration",
                },
                "esm2_source": {
                    "source_revision": SIMPLEFOLD_ESM2_REVISION,
                    "source_tree_sha256": SIMPLEFOLD_ESM2_SOURCE_TREE_SHA256,
                    "path_source": "trusted_environment_configuration",
                },
                "esm2_models": {
                    "artifact_sha256": dict(
                        sorted(SIMPLEFOLD_ESM2_ARTIFACT_SHA256.items())
                    ),
                    "path_source": "trusted_environment_configuration",
                },
                "device": {
                    "source": "trusted_environment_configuration",
                    "exact_value": SIMPLEFOLD_DEVICE,
                },
                "runtime_fingerprint": {
                    "source": "trusted_environment_configuration",
                    "safe_public_identity": True,
                },
            },
            check=_simplefold_ready,
        ),
        deterministic=False,
        cacheable=False,
        implementation_identity={
            "name": "folding.simplefold.local-adapter",
            "model": SIMPLEFOLD_MODEL,
            "source_revision": SIMPLEFOLD_REVISION,
            "device": SIMPLEFOLD_DEVICE,
            "seed_control": "torch_local",
            "determinism_contract": (
                "one exact Torch seed per parent batched call derived from "
                "configured base seed, canonical parent sequence content "
                "digest, and parent slot; sample slots follow provider order; "
                "no cross-device bitwise guarantee"
            ),
            "cache_policy": (
                "runtime-device-specific_diffusion_not_cacheable"
            ),
            "staging_policy": "private-per-engine-invocation-cleaned",
        },
        effective_randomness_parameters=("effective_seed",),
        effective_randomness_resolver=EffectiveRandomnessResolver(
            behavior=BehaviorReference(
                "folding.simplefold_local/effective-randomness",
                _FOLD_NODE_BINDING_VERSION,
                {
                    "provider_seed_control": "torch_local",
                    "seed_scope": (
                        "scientific-input-content-and-parent-slot"
                    ),
                    "sample_order": "parent-then-zero-based-sample",
                },
            ),
            resolve=_resolve_simplefold_effective_randomness,
        ),
    )


def _simplefold_confidence_binding() -> ExecutionBindingDefinition:
    method_id = (
        "folding.simplefold_confidence."
        "existing_structure_1_6b_c7a5570"
    )
    return ExecutionBindingDefinition(
        binding_id="folding.simplefold_confidence.simplefold_local",
        version=_CONFIDENCE_NODE_BINDING_VERSION,
        node_type=ContractIdentity(
            "node_type",
            "folding.simplefold_confidence",
            _CONFIDENCE_NODE_BINDING_VERSION,
        ),
        method=ContractIdentity(
            "method",
            method_id,
            CONFIDENCE_METHOD_VERSION,
        ),
        binding_parameters={},
        execution_route="adapter",
        factory=ScientificOperationFactory(
            behavior=BehaviorReference(
                "folding.simplefold_confidence/factory",
                _CONFIDENCE_NODE_BINDING_VERSION,
                {
                    "route": "simplefold_local",
                    "operation": "existing_structure_confidence",
                    "engine_identity": "exact_method_contract_digest",
                },
            ),
            build=_build_simplefold_confidence,
        ),
        adapter_behavior=BehaviorReference(
            "folding.simplefold_confidence/adapter",
            _CONFIDENCE_NODE_BINDING_VERSION,
            {
                "adapter_identity": SIMPLEFOLD_CONFIDENCE_ADAPTER,
                "provider_contract": (
                    f"ml-simplefold@{SIMPLEFOLD_REVISION}"
                ),
                "featurization": SIMPLEFOLD_CONFIDENCE_FEATURIZATION,
                "native_scale": "[0,1]_multiply_100",
                "coordinate_operation": "existing_input_only_no_refold",
                "esm2_operation": "representations_only_no_contacts",
                "engine_identity": "exact_method_contract_digest",
            },
        ),
        availability=AvailabilityDeclaration(
            behavior=BehaviorReference(
                "folding.simplefold_confidence/availability",
                _CONFIDENCE_NODE_BINDING_VERSION,
                {"observation": "startup", "model_load": "forbidden"},
            ),
            prerequisites={
                "provider": {
                    "name": "simplefold",
                    "source_revision": SIMPLEFOLD_REVISION,
                },
                "runtime": {"name": "torch"},
            },
            check=_simplefold_confidence_available,
        ),
        readiness=ReadinessDeclaration(
            behavior=BehaviorReference(
                "folding.simplefold_confidence/readiness",
                _CONFIDENCE_NODE_BINDING_VERSION,
                {
                    "observation": "per-run",
                    "cache_order": "before-cache-lookup",
                    "model_load": "forbidden",
                    "asset_closure": "exact-confidence-only",
                },
            ),
            prerequisites={
                "simplefold_confidence_models": {
                    "artifact_sha256": (
                        simplefold_confidence_artifact_sha256()
                    ),
                    "runtime_names": {
                        "plddt_module_1.6B.ckpt": "plddt.ckpt",
                    },
                    "path_source": "trusted_environment_configuration",
                },
                "esm2_source": {
                    "source_revision": SIMPLEFOLD_ESM2_REVISION,
                    "source_tree_sha256": SIMPLEFOLD_ESM2_SOURCE_TREE_SHA256,
                    "operation": "representation_only_no_contacts",
                    "path_source": "trusted_environment_configuration",
                },
                "esm2_model": {
                    "artifact_sha256": (
                        simplefold_confidence_esm2_artifact_sha256()
                    ),
                    "path_source": "trusted_environment_configuration",
                },
                "device": {
                    "source": "trusted_environment_configuration",
                    "exact_value": SIMPLEFOLD_CONFIDENCE_DEVICE,
                },
                "runtime_fingerprint": {
                    "source": "trusted_environment_configuration",
                    "configured_value": confidence_runtime_fingerprint(),
                    "safe_public_identity": True,
                },
            },
            check=_simplefold_confidence_ready,
        ),
        deterministic=True,
        cacheable=True,
        implementation_identity={
            "name": SIMPLEFOLD_CONFIDENCE_ADAPTER,
            "operation": "existing_structure_confidence_no_refold",
            "device": SIMPLEFOLD_CONFIDENCE_DEVICE,
            "featurization": SIMPLEFOLD_CONFIDENCE_FEATURIZATION,
            "simplefold_artifact_sha256": (
                simplefold_confidence_artifact_sha256()
            ),
            "esm2_artifact_sha256": (
                simplefold_confidence_esm2_artifact_sha256()
            ),
            "source_revision": SIMPLEFOLD_REVISION,
            "native_scale": "[0,1]_multiply_100",
        },
        produced_observations=tuple(
            ProducedObservationDefinition(
                output_port="confidence_observations",
                metric=ContractIdentity(
                    "metric",
                    metric,
                    _METRIC_VERSIONS[metric],
                ),
                context_profile={"kind": "intrinsic"},
                subject_grain="candidate",
                source_role="subject",
                subject_direction="input",
                subject_port="structure_candidates",
                axis_direction="input",
                axis_port="structure_residue_axes",
                guaranteed_multiplicity="one",
                output_partition="existing_structure_confidence",
            )
            for metric in (
                "structure.plddt.per_residue",
                "structure.plddt.mean_residue",
            )
        ),
    )


MODULE_PACKAGE = ModulePackageRegistration(
    schema_version="2.1.0",
    package_id="folding",
    package_version=_PACKAGE_VERSION,
    package_module=__package__,
    node_definitions=(
        DefinitionResource("definitions/fold.yaml"),
        DefinitionResource("definitions/simplefold_confidence.yaml"),
    ),
    methods=(
        REMOTE_ESMFOLD2_FOLD_METHOD,
        LOCAL_ESMFOLD2_FOLD_METHOD,
        SIMPLEFOLD_FOLD_METHOD,
        SIMPLEFOLD_CONFIDENCE_METHOD,
    ),
    bindings=(
        _binding("remote"),
        _binding("local"),
        _simplefold_binding(),
        _simplefold_confidence_binding(),
    ),
)
