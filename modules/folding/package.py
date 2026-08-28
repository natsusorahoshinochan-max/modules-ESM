"""The single production registration for shared protein folding."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from core.catalog.declarations import (
    AvailabilityDeclaration,
    AvailabilityResult,
    ContractIdentity,
    EffectiveRandomnessResolver,
    EnvironmentFieldDeclaration,
    ExecutionBindingDefinition,
    ModulePackageRegistration,
    ProducedObservationDefinition,
    ReadinessDeclaration,
    ScientificOperationFactory,
)
from core.catalog.definition_resource import (
    DefinitionResource,
)
from core.catalog.port_contract import (
    BehaviorReference,
)
from core.operation import (
    AdmittedPort,
    BindingEnvironment,
    OperationContext,
    ReadinessResult,
    ScientificOperation,
)
from core.local_torch_device import LOCAL_TORCH_DEVICE_POLICY

from . import simplefold_contract
from .contracts import (
    LOCAL_ESMFOLD2_FOLD_METHOD,
    REMOTE_ESMFOLD2_FOLD_METHOD,
    SIMPLEFOLD_CONFIDENCE_METHOD,
    SIMPLEFOLD_FOLD_METHOD,
)

from .esmfold2_contract import (
    LOCAL_ESMC_MODEL,
    LOCAL_ESMC_PRECISION,
    LOCAL_ESMFOLD2_MODEL,
    REMOTE_ESMFOLD2_MODEL,
)
from .esmfold2_local import (
    LOCAL_ESMFOLD2_LANGUAGE_MODEL_SNAPSHOT_FILES,
    LOCAL_ESMFOLD2_MODEL_SNAPSHOT_FILES,
    LocalESMFold2Adapter,
    local_readiness,
    local_runtime_structurally_available,
)
from .esmfold2_remote import (
    BiohubESMFold2Adapter,
    remote_readiness,
    remote_runtime_structurally_available,
)
from .simplefold_adapter import (
    LocalSimpleFoldAdapter,
    simplefold_readiness,
    simplefold_runtime_structurally_available,
)
from .simplefold_confidence_adapter import (
    LocalSimpleFoldConfidenceAdapter,
    simplefold_confidence_readiness,
    simplefold_confidence_runtime_structurally_available,
)
from .simplefold_contract import (
    SIMPLEFOLD_CONFIDENCE_ADAPTER,
    SIMPLEFOLD_CONFIDENCE_FEATURIZATION,
    SIMPLEFOLD_MODEL,
)


_BIOHUB_ENVIRONMENT_FIELDS = (
    EnvironmentFieldDeclaration("credential_handle", "credential_handle"),
)
_LOCAL_ESMFOLD2_ENVIRONMENT_FIELDS = (
    EnvironmentFieldDeclaration("model_snapshot_path", "filesystem_path"),
    EnvironmentFieldDeclaration(
        "language_model_snapshot_path",
        "filesystem_path",
    ),
)
_SIMPLEFOLD_ENVIRONMENT_FIELDS = (
    EnvironmentFieldDeclaration("model_root", "filesystem_path"),
    EnvironmentFieldDeclaration("esm2_source_root", "filesystem_path"),
    EnvironmentFieldDeclaration("esm2_model_root", "filesystem_path"),
)




def _remote_ready(check_input: BindingEnvironment) -> ReadinessResult:
    del check_input
    passing = remote_readiness()
    return ReadinessResult(
        passing,
        reason_code=(None if passing else "remote_runtime_unavailable"),
    )


def _local_ready(check_input: BindingEnvironment) -> ReadinessResult:
    return local_readiness(check_input.values)


def _simplefold_ready(
    check_input: BindingEnvironment,
) -> ReadinessResult:
    return simplefold_readiness(check_input.values)


def _simplefold_confidence_ready(
    check_input: BindingEnvironment,
) -> ReadinessResult:
    return simplefold_confidence_readiness(check_input.values)


def _remote_available() -> AvailabilityResult:
    if not remote_runtime_structurally_available():
        return AvailabilityResult.unavailable(
            code="remote_esmfold2_runtime_unavailable",
            message="The remote ESMFold2 SDK runtime is unavailable.",
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
    inputs: Mapping[str, AdmittedPort],
    node_parameters: Mapping[str, Any],
    binding_parameters: Mapping[str, Any],
) -> dict[str, Any]:
    del inputs, binding_parameters
    return {"effective_seed": node_parameters["effective_seed"]}


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
        binding_id = "folding.fold.esmfold2_remote"
        method_id = "folding.fold.esmfold2_fast_biohub_2026_05"
        model = REMOTE_ESMFOLD2_MODEL
        availability = AvailabilityDeclaration(
            behavior=BehaviorReference(
                "folding.esmfold2_remote/availability",
                {"observation": "startup"},
            ),
            prerequisites={"provider_sdk": {"name": "esm"}},
            check=_remote_available,
        )
        readiness = ReadinessDeclaration(
            behavior=BehaviorReference(
                "folding.esmfold2_remote/readiness",
                {
                    "observation": "cache-miss",
                    "cache_order": "before-provider-entry",
                    "secret_retention": "none",
                },
            ),
            prerequisites={
                "credential": {
                    "source": "trusted_environment_configuration",
                },
                "provider_sdk": {"name": "esm"},
            },
            check=_remote_ready,
        )
        adapter_details = {
            "provider_contract": "esm-sdk-fold",
            "native_scale": "[0,1]_multiply_100",
            "engine_identity": "stable_method_id",
            "randomness_evidence": "provider_uncontrolled",
        }
    else:
        binding_id = "folding.fold.esmfold2_local"
        method_id = "folding.fold.esmfold2_hf_1ebf0e3"
        model = LOCAL_ESMFOLD2_MODEL
        availability = AvailabilityDeclaration(
            behavior=BehaviorReference(
                "folding.esmfold2_local/availability",
                {"observation": "startup", "model_load": "forbidden"},
            ),
            prerequisites={
                "provider_sdk": {"name": "esm"},
                "transformers": {"name": "transformers"},
                "torch": {"name": "torch"},
            },
            check=_local_available,
        )
        readiness = ReadinessDeclaration(
            behavior=BehaviorReference(
                "folding.esmfold2_local/readiness",
                {
                    "observation": "cache-miss",
                    "cache_order": "before-provider-entry",
                    "secret_retention": "none",
                },
            ),
            prerequisites={
                "model_snapshot": {
                    "source": LOCAL_ESMFOLD2_MODEL,
                    "path_source": "trusted_environment_configuration",
                    "required_relative_files": (
                        LOCAL_ESMFOLD2_MODEL_SNAPSHOT_FILES
                    ),
                },
                "language_model_snapshot": {
                    "source": LOCAL_ESMC_MODEL,
                    "precision": LOCAL_ESMC_PRECISION,
                    "path_source": "trusted_environment_configuration",
                    "required_relative_files": (
                        LOCAL_ESMFOLD2_LANGUAGE_MODEL_SNAPSHOT_FILES
                    ),
                },
                "device": {
                    "source": "adapter",
                    "policy": LOCAL_TORCH_DEVICE_POLICY,
                    "fallback": "forbidden",
                },
            },
            check=_local_ready,
        )
        adapter_details = {
            "provider_contract": "esmfold2-huggingface-local",
            "native_scale": "[0,1]_multiply_100",
            "engine_identity": "stable_method_id",
            "randomness_evidence": "exact_seed",
            "provider_seed_domain": "unsigned_32_bit",
            "language_model_precision": LOCAL_ESMC_PRECISION,
        }
        seed_control = "python_numpy_mt19937_torch_shared"
        seed_scope = "scientific-input-content-and-parent-sample-slot"
    return ExecutionBindingDefinition(
        binding_id=binding_id,
        node_type=ContractIdentity(
            "node_type",
            "folding.fold",
        ),
        method=ContractIdentity(
            "method",
            method_id,
        ),
        binding_parameters={},
        environment_fields=(
            _BIOHUB_ENVIRONMENT_FIELDS
            if route == "remote"
            else _LOCAL_ESMFOLD2_ENVIRONMENT_FIELDS
        ),
        execution_route="adapter",
        factory=ScientificOperationFactory(
            behavior=BehaviorReference(
                "folding.fold/factory",
                {"route": route, "model": model},
            ),
            build=_build_remote if route == "remote" else _build_local,
        ),
        adapter_behavior=BehaviorReference(
            f"folding.esmfold2_{route}/adapter",
            adapter_details,
        ),
        availability=availability,
        readiness=readiness,
        deterministic=False,
        cacheable=False,
        effective_randomness_parameters=(
            () if route == "remote" else ("effective_seed",)
        ),
        effective_randomness_resolver=(
            None
            if route == "remote"
            else EffectiveRandomnessResolver(
                behavior=BehaviorReference(
                    f"folding.esmfold2_{route}/effective-randomness",
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
    closure = simplefold_contract.SIMPLEFOLD_FOLDING_ASSET_CLOSURE
    return ExecutionBindingDefinition(
        binding_id="folding.fold.simplefold_local",
        node_type=ContractIdentity(
            "node_type",
            "folding.fold",
        ),
        method=ContractIdentity(
            "method",
            method_id,
        ),
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
        environment_fields=_SIMPLEFOLD_ENVIRONMENT_FIELDS,
        execution_route="adapter",
        factory=ScientificOperationFactory(
            behavior=BehaviorReference(
                "folding.fold/factory",
                {"route": "simplefold_local", "model": SIMPLEFOLD_MODEL},
            ),
            build=_build_simplefold,
        ),
        adapter_behavior=BehaviorReference(
            "folding.simplefold_local/adapter",
            {
                "provider_contract": "ml-simplefold",
                "native_scale": "[0,100]_identity",
                "staging": "one-private-directory-per-adapter-call",
                "engine_identity": "stable_method_id",
                "randomness_evidence": "exact_seed",
                "pdb_translation": (
                    "pinned-padded-sentinel-to-canonical-END-newline"
                ),
            },
        ),
        availability=AvailabilityDeclaration(
            behavior=BehaviorReference(
                "folding.simplefold_local/availability",
                {"observation": "startup", "model_load": "forbidden"},
            ),
            prerequisites={
                "provider": {"name": "simplefold"},
                "runtime": {"name": "torch"},
            },
            check=_simplefold_available,
        ),
        readiness=ReadinessDeclaration(
            behavior=BehaviorReference(
                "folding.simplefold_local/readiness",
                {
                    "observation": "cache-miss",
                    "cache_order": "before-provider-entry",
                    "model_load": "forbidden",
                },
            ),
            prerequisites={
                "provider_asset_closure": closure.readiness_prerequisite(),
                "device": {
                    "source": "adapter",
                    "policy": LOCAL_TORCH_DEVICE_POLICY,
                    "fallback": "forbidden",
                },
            },
            check=_simplefold_ready,
        ),
        deterministic=False,
        cacheable=False,
        effective_randomness_parameters=("effective_seed",),
        effective_randomness_resolver=EffectiveRandomnessResolver(
            behavior=BehaviorReference(
                "folding.simplefold_local/effective-randomness",
                {
                    "provider_seed_control": "torch_local",
                    "seed_scope": (
                        "scientific-input-content-and-parent-slot"
                    ),
                    "sample_order": "parent-then-zero-based-sample",
                },
            ),
            resolve=_resolve_effective_randomness,
        ),
    )


def _simplefold_confidence_binding() -> ExecutionBindingDefinition:
    method_id = (
        "folding.simplefold_confidence."
        "existing_structure_1_6b_c7a5570"
    )
    closure = simplefold_contract.SIMPLEFOLD_CONFIDENCE_ASSET_CLOSURE
    return ExecutionBindingDefinition(
        binding_id="folding.simplefold_confidence.simplefold_local",
        node_type=ContractIdentity(
            "node_type",
            "folding.simplefold_confidence",
        ),
        method=ContractIdentity(
            "method",
            method_id,
        ),
        binding_parameters={},
        environment_fields=_SIMPLEFOLD_ENVIRONMENT_FIELDS,
        execution_route="adapter",
        factory=ScientificOperationFactory(
            behavior=BehaviorReference(
                "folding.simplefold_confidence/factory",
                {
                    "route": "simplefold_local",
                    "operation": "existing_structure_confidence",
                    "engine_identity": "stable_method_id",
                },
            ),
            build=_build_simplefold_confidence,
        ),
        adapter_behavior=BehaviorReference(
            "folding.simplefold_confidence/adapter",
            {
                "adapter_identity": SIMPLEFOLD_CONFIDENCE_ADAPTER,
                "provider_contract": "ml-simplefold",
                "featurization": SIMPLEFOLD_CONFIDENCE_FEATURIZATION,
                "native_scale": "[0,1]_multiply_100",
                "coordinate_operation": "existing_input_only_no_refold",
                "esm2_operation": "representations_only_no_contacts",
                "engine_identity": "stable_method_id",
            },
        ),
        availability=AvailabilityDeclaration(
            behavior=BehaviorReference(
                "folding.simplefold_confidence/availability",
                {"observation": "startup", "model_load": "forbidden"},
            ),
            prerequisites={
                "provider": {"name": "simplefold"},
                "runtime": {"name": "torch"},
            },
            check=_simplefold_confidence_available,
        ),
        readiness=ReadinessDeclaration(
            behavior=BehaviorReference(
                "folding.simplefold_confidence/readiness",
                {
                    "observation": "cache-miss",
                    "cache_order": "before-provider-entry",
                    "model_load": "forbidden",
                    "asset_closure": "exact-confidence-only",
                },
            ),
            prerequisites={
                "provider_asset_closure": closure.readiness_prerequisite(),
                "device": {
                    "source": "adapter",
                    "policy": LOCAL_TORCH_DEVICE_POLICY,
                    "fallback": "forbidden",
                },
            },
            check=_simplefold_confidence_ready,
        ),
        deterministic=True,
        cacheable=True,
        produced_observations=tuple(
            ProducedObservationDefinition(
                output_port="confidence_observations",
                metric=ContractIdentity(
                    "metric",
                    metric,
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
    package_id="folding",
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
