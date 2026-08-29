"""The single production registration for remote and local ESM-3 generation."""

from __future__ import annotations

from collections.abc import Callable, Mapping
import importlib.util
from typing import Any

from core.catalog.declarations import (
    AvailabilityDeclaration,
    AvailabilityResult,
    ContractIdentity,
    EffectiveRandomnessResolver,
    EnvironmentFieldDeclaration,
    ExecutionBindingDefinition,
    MethodDefinition,
    ModulePackageRegistration,
    ReadinessDeclaration,
    ScientificOperationFactory,
)
from core.catalog.definition_resource import (
    DefinitionResource,
)
from core.catalog.port_contract import BehaviorReference
from core.operation import (
    AdmittedPort,
    BindingEnvironment,
    OperationContext,
    ReadinessResult,
    ScientificOperation,
)
from core.local_torch_device import LOCAL_TORCH_DEVICE_POLICY
from .adapter import (
    BIOHUB_ESM3_MEDIUM_MODEL,
    BIOHUB_ESM3_OPEN_MODEL,
    BiohubESM3Adapter,
)
from .implementation import ESM3GenerationOperation
from .esmc_implementation import ESMCRepresentationOperation
from .domain import (
    ESMC_MEAN_EMBEDDING_DIMENSION,
    ESMC_SEQUENCE_LOGITS_DIMENSION,
)
from .esmc_adapter import (
    BIOHUB_ESMC_MODEL,
    BiohubESMCAdapter,
)
from . import port_types as _port_types
from .local_adapter import (
    LOCAL_ESM3_MODEL,
    LOCAL_ESM3_LSH_TABLE_PATH,
    LOCAL_ESM3_PACKAGE_ASSET_FILES,
    LOCAL_ESM3_RESIDUE_ANNOTATIONS_PATH,
    LOCAL_ESM3_SNAPSHOT_SOURCE,
    LOCAL_ESM3_WEIGHT_FILES,
    LocalESM3Adapter,
    local_readiness,
    local_runtime_structurally_available,
)


_OPERATIONS = (
    "generate_sequence",
    "generate_structure",
    "generate_paired",
)
_MODELS = (
    {
        "suffix": "medium_2024_08",
        "route": "biohub_medium",
        "model": BIOHUB_ESM3_MEDIUM_MODEL,
        "scale": "medium",
        "release": "2024-08",
    },
    {
        "suffix": "open_2024_03",
        "route": "biohub_open",
        "model": BIOHUB_ESM3_OPEN_MODEL,
        "scale": "open",
        "release": "2024-03",
    },
)
_LOCAL_MODEL = {
    "suffix": "sm_open_v1_local",
    "route": "local_open",
    "model": LOCAL_ESM3_MODEL,
    "scale": "small-open",
    "release": "esm3-sm-open-v1",
}
_BIOHUB_ENVIRONMENT_FIELDS = (
    EnvironmentFieldDeclaration("credential_handle", "credential_handle"),
)
_LOCAL_ENVIRONMENT_FIELDS = (
    EnvironmentFieldDeclaration("model_snapshot_path", "filesystem_path"),
)


def _build_esmc(context: OperationContext) -> ESMCRepresentationOperation:
    return ESMCRepresentationOperation(
        BiohubESMCAdapter(
            environment=context.environment,
            resources=context.resources,
            model_name=BIOHUB_ESMC_MODEL,
        )
    )


def _esmc_method() -> MethodDefinition:
    return MethodDefinition(
        method_id="esm3.represent_sequence.esmc_600m_2024_12",
        algorithm_identity={
            "name": "ESMC masked-language-model sequence representation",
            "provider_operations": ("encode", "logits"),
            "logits_request": {
                "sequence": True,
                "return_mean_embedding": True,
            },
            "published_value": (
                "Provider-normalized mean embedding and sequence-logits "
                "shape on the CLS, residue-token, EOS axis"
            ),
        },
        model_identity={
            "model": BIOHUB_ESMC_MODEL,
            "source": "Biohub",
            "scale": "600M",
            "release": "2024-12",
        },
        featurization_identity={
            "input": "ESMProtein complete sequence",
            "tokenization": "Biohub ESMC encode endpoint",
            "residue_axis": "input order preserved",
        },
        scale_contract={
            "mean_embedding": {
                "storage": "provider_normalized_binary32",
                "dimension": ESMC_MEAN_EMBEDDING_DIMENSION,
            },
            "sequence_logits": {
                "storage": "validated_shape_only_not_persisted",
                "shape": "L_plus_2_by_64",
                "axis": "CLS_then_residue_tokens_then_EOS",
                "model_head_class_width": ESMC_SEQUENCE_LOGITS_DIMENSION,
            },
        },
    )


def _esmc_binding() -> ExecutionBindingDefinition:
    return ExecutionBindingDefinition(
        binding_id=(
            "esm3.represent_sequence.biohub_esmc_600m_2024_12"
        ),
        node_type=ContractIdentity(
            "node_type",
            "esm3.represent_sequence",
        ),
        method=ContractIdentity(
            "method",
            "esm3.represent_sequence.esmc_600m_2024_12",
        ),
        binding_parameters={},
        environment_fields=_BIOHUB_ENVIRONMENT_FIELDS,
        execution_route="adapter",
        factory=ScientificOperationFactory(
            behavior=BehaviorReference(
                "esm3.represent_sequence/factory",
                {
                    "route": "biohub",
                    "model": BIOHUB_ESMC_MODEL,
                    "engine_identity": "stable_method_id",
                },
            ),
            build=_build_esmc,
        ),
        adapter_behavior=BehaviorReference(
            "esm3.biohub_esmc/adapter",
            {
                "provider_contract": "esm-sdk-encode+logits",
                "output_contract": "mean-embedding-1152+logits-L+2x64",
                "engine_identity": "stable_method_id",
            },
        ),
        availability=AvailabilityDeclaration(
            behavior=BehaviorReference(
                "esm3.biohub_esmc/availability",
                {"observation": "startup"},
            ),
            prerequisites={"provider_sdk": {"name": "esm"}},
            check=_available,
        ),
        readiness=ReadinessDeclaration(
            behavior=BehaviorReference(
                "esm3.biohub_esmc/readiness",
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
            check=_ready,
        ),
        deterministic=True,
        cacheable=True,
    )


def _available() -> AvailabilityResult:
    if (
        importlib.util.find_spec("esm") is not None
        and importlib.util.find_spec("esm.sdk") is not None
    ):
        return AvailabilityResult.available()
    return AvailabilityResult.unavailable(
        code="esm_sdk_unavailable",
        message="The ESM SDK installation is unavailable.",
        retryable=False,
    )


def _local_available() -> AvailabilityResult:
    if local_runtime_structurally_available():
        return AvailabilityResult.available()
    return AvailabilityResult.unavailable(
        code="local_esm3_runtime_unavailable",
        message=(
            "The local ESM SDK and Torch runtime prerequisites are "
            "unavailable."
        ),
        retryable=False,
    )


def _ready(check_input: BindingEnvironment) -> ReadinessResult:
    del check_input
    if (
        importlib.util.find_spec("esm") is None
        or importlib.util.find_spec("esm.sdk") is None
    ):
        return ReadinessResult(
            False,
            reason_code="esm_sdk_unavailable",
        )
    return ReadinessResult(True)


def _local_ready(check_input: BindingEnvironment) -> ReadinessResult:
    return local_readiness(check_input.values)


def _resolve_local_effective_randomness(
    *,
    inputs: Mapping[str, AdmittedPort],
    node_parameters: Mapping[str, Any],
    binding_parameters: Mapping[str, Any],
) -> dict[str, Any]:
    del inputs, binding_parameters
    return {"effective_seed": node_parameters["effective_seed"]}


def _build(
    operation: str,
    *,
    model_name: str,
) -> Callable[[OperationContext], ScientificOperation]:
    def factory(context: OperationContext) -> ESM3GenerationOperation:
        adapter = BiohubESM3Adapter(
            environment=context.environment,
            resources=context.resources,
            model_name=model_name,
        )
        return ESM3GenerationOperation(
            adapter=adapter,
            operation=operation,
            method=context.method,
        )

    return factory


def _build_local(
    operation: str,
    *,
    model_name: str,
) -> Callable[[OperationContext], ScientificOperation]:
    def factory(context: OperationContext) -> ESM3GenerationOperation:
        adapter = LocalESM3Adapter(
            environment=context.environment,
            resources=context.resources,
            model_name=model_name,
        )
        return ESM3GenerationOperation(
            adapter=adapter,
            operation=operation,
            method=context.method,
        )

    return factory


def _method(
    operation: str,
    model: Mapping[str, str],
) -> MethodDefinition:
    provider_operation = {
        "generate_sequence": "generate(track=sequence)",
        "generate_structure": "generate(track=structure)",
        "generate_paired": (
            "generate(track=sequence) then generate(track=structure)"
        ),
    }[operation]
    method_id = f"esm3.{operation}.esm3_{model['suffix']}"
    return MethodDefinition(
        method_id=method_id,
        algorithm_identity={
            "name": "ESM-3 iterative masked-track generation",
            "operation": provider_operation,
            "condition_on_coordinates_only": True,
            "pairing": (
                "one terminal sequence to one structure counterpart"
                if operation == "generate_paired"
                else "not_applicable"
            ),
            "randomness_contract": (
                "Biohub exposes no seed control; every Engine Invocation is "
                "recorded as provider-uncontrolled and no effective seed is "
                "published"
            ),
            "step_count_contract": {
                "requested": "num_steps is an upper bound",
                "effective": (
                    "official Forge clamps the request to the encoded "
                    "sequence length"
                ),
                "evidence": (
                    "requested and effective num_steps recorded per call"
                ),
            },
        },
        model_identity={
            "model": model["model"],
            "source": "Biohub",
            "scale": model["scale"],
            "release": model["release"],
        },
        featurization_identity={
            "input": "ESMProtein",
            "sequence_masks": "_",
            "secondary_structure": "SS8-with-DSSP-coil-to-C",
            "structure": "atom37",
            "function_intervals": "one-based-inclusive",
            "confidence_axis": (
                "exact ProteinPrompt input reference, target layout, and "
                "provider-returned complete sequence"
            ),
        },
        scale_contract={
            "ptm": "provider_native_[0,1]",
            "plddt": "provider_native_[0,1]_multiply_100",
            "pae": "provider_native_angstrom",
            "provider_tensor_shapes": {
                "ptm": "scalar",
                "plddt": "L",
                "pae": "L_by_L_or_none",
            },
        },
    )


def _local_method(
    operation: str,
) -> MethodDefinition:
    provider_operation = {
        "generate_sequence": "generate(track=sequence)",
        "generate_structure": "generate(track=structure)",
        "generate_paired": (
            "generate(track=sequence) then generate(track=structure)"
        ),
    }[operation]
    return MethodDefinition(
        method_id=f"esm3.{operation}.esm3_sm_open_v1_local",
        algorithm_identity={
            "name": "ESM-3 iterative masked-track generation",
            "operation": provider_operation,
            "condition_on_coordinates_only": True,
            "pairing": (
                "one terminal sequence to one structure counterpart"
                if operation == "generate_paired"
                else "not_applicable"
            ),
            "determinism_contract": (
                "exact Torch seed derived from configured base seed, canonical "
                "ProteinPrompt content digest, and zero-based sample-track "
                "slot; exact outputs are runtime-device-specific and are not "
                "cacheable"
            ),
            "step_count_contract": {
                "requested": "num_steps is an upper bound",
                "effective": (
                    "official local generation clamps the request to the "
                    "number of sampled positions for the selected track"
                ),
                "evidence": (
                    "requested and effective num_steps recorded per call"
                ),
            },
        },
        model_identity={
            "model": LOCAL_ESM3_MODEL,
            "source": LOCAL_ESM3_SNAPSHOT_SOURCE,
            "scale": _LOCAL_MODEL["scale"],
            "release": _LOCAL_MODEL["release"],
        },
        featurization_identity={
            "input": "ESMProtein",
            "sequence_masks": "_",
            "secondary_structure": "SS8-with-DSSP-coil-to-C",
            "structure": "atom37",
            "function_intervals": "one-based-inclusive",
            "confidence_axis": (
                "exact ProteinPrompt input reference, target layout, and "
                "provider-returned complete sequence"
            ),
        },
        scale_contract={
            "ptm": "provider_native_[0,1]",
            "plddt": "provider_native_[0,1]_multiply_100",
            "pae": "provider_native_angstrom",
            "provider_tensor_shapes": {
                "ptm": "singleton_1",
                "plddt": "L_after_SDK_BOS_EOS_removal",
                "pae": "1_by_L_plus_2_by_L_plus_2_or_none",
                "pae_translation": (
                    "select_batch_0_then_remove_BOS_and_EOS"
                ),
            },
        },
    )


def _binding(
    operation: str,
    model: Mapping[str, str],
) -> ExecutionBindingDefinition:
    method_id = f"esm3.{operation}.esm3_{model['suffix']}"
    return ExecutionBindingDefinition(
        binding_id=f"esm3.{operation}.{model['route']}",
        node_type=ContractIdentity(
            "node_type",
            f"esm3.{operation}",
        ),
        method=ContractIdentity(
            "method",
            method_id,
        ),
        binding_parameters={},
        environment_fields=_BIOHUB_ENVIRONMENT_FIELDS,
        execution_route="adapter",
        factory=ScientificOperationFactory(
            behavior=BehaviorReference(
                f"esm3.{operation}/factory",
                {
                    "route": "biohub",
                    "model": model["model"],
                },
            ),
            build=_build(
                operation,
                model_name=model["model"],
            ),
        ),
        adapter_behavior=BehaviorReference(
            "esm3.biohub/adapter",
            {
                "provider_contract": "esm-sdk-generate",
                "track_translation": "documented-provider-output",
                "engine_identity": "stable_method_id",
                "randomness_evidence": "provider_uncontrolled",
            },
        ),
        availability=AvailabilityDeclaration(
            behavior=BehaviorReference(
                "esm3.biohub/availability",
                {"observation": "startup"},
            ),
            prerequisites={"provider_sdk": {"name": "esm"}},
            check=_available,
        ),
        readiness=ReadinessDeclaration(
            behavior=BehaviorReference(
                "esm3.biohub/readiness",
                {
                    "observation": "cache-miss",
                    "secret_retention": "none",
                },
            ),
            prerequisites={
                "credential": {
                    "source": "trusted_environment_configuration",
                },
                "provider_sdk": {"name": "esm"},
            },
            check=_ready,
        ),
        deterministic=False,
        cacheable=False,
    )


def _local_binding(operation: str) -> ExecutionBindingDefinition:
    method_id = f"esm3.{operation}.esm3_sm_open_v1_local"
    return ExecutionBindingDefinition(
        binding_id=f"esm3.{operation}.local_open",
        node_type=ContractIdentity(
            "node_type",
            f"esm3.{operation}",
        ),
        method=ContractIdentity(
            "method",
            method_id,
        ),
        binding_parameters={},
        environment_fields=_LOCAL_ENVIRONMENT_FIELDS,
        execution_route="adapter",
        factory=ScientificOperationFactory(
            behavior=BehaviorReference(
                f"esm3.{operation}/factory",
                {
                    "route": "local_open",
                    "model": LOCAL_ESM3_MODEL,
                },
            ),
            build=_build_local(
                operation,
                model_name=LOCAL_ESM3_MODEL,
            ),
        ),
        adapter_behavior=BehaviorReference(
            "esm3.local_open/adapter",
            {
                "provider_contract": (
                    "esm-sdk-local-generate"
                ),
                "track_translation": "documented-provider-output",
                "engine_identity": "stable_method_id",
                "seed_control": (
                    "exact-torch-seed-from-input-content-and-sample-track-slot"
                ),
                "randomness_evidence": "exact_seed",
            },
        ),
        availability=AvailabilityDeclaration(
            behavior=BehaviorReference(
                "esm3.local_open/availability",
                {
                    "observation": "startup",
                    "model_load": "forbidden",
                },
            ),
            prerequisites={
                "provider_sdk": {"name": "esm"},
                "runtime": {"name": "torch"},
            },
            check=_local_available,
        ),
        readiness=ReadinessDeclaration(
            behavior=BehaviorReference(
                "esm3.local_open/readiness",
                {
                    "observation": "cache-miss",
                    "secret_retention": "none",
                    "cache_order": "before-provider-entry",
                },
            ),
            prerequisites={
                "model_snapshot": {
                    "source": LOCAL_ESM3_SNAPSHOT_SOURCE,
                    "path_source": "trusted_environment_configuration",
                    "required_relative_files": (
                        *LOCAL_ESM3_WEIGHT_FILES,
                        LOCAL_ESM3_LSH_TABLE_PATH,
                        LOCAL_ESM3_RESIDUE_ANNOTATIONS_PATH,
                    ),
                },
                "device": {
                    "source": "adapter",
                    "policy": LOCAL_TORCH_DEVICE_POLICY,
                    "fallback": "forbidden",
                },
                "provider_sdk": {
                    "name": "esm",
                    "required_relative_files": LOCAL_ESM3_PACKAGE_ASSET_FILES,
                },
            },
            check=_local_ready,
        ),
        deterministic=False,
        cacheable=False,
        effective_randomness_parameters=("effective_seed",),
        effective_randomness_resolver=EffectiveRandomnessResolver(
            behavior=BehaviorReference(
                "esm3.local/effective-randomness",
                {
                    "provider_seed_control": "torch_local",
                    "sample_order": "zero-based",
                    "seed_scope": (
                        "scientific-input-content-and-sample-track-slot"
                    ),
                },
            ),
            resolve=_resolve_local_effective_randomness,
        ),
    )


MODULE_PACKAGE = ModulePackageRegistration(
    package_id="esm3",
    package_module=__package__,
    node_definitions=(
        DefinitionResource("definitions/generate_sequence.yaml"),
        DefinitionResource("definitions/generate_structure.yaml"),
        DefinitionResource("definitions/generate_paired.yaml"),
        DefinitionResource("definitions/represent_sequence.yaml"),
    ),
    methods=tuple(
        _method(operation, model)
        for model in _MODELS
        for operation in _OPERATIONS
    ) + tuple(_local_method(operation) for operation in _OPERATIONS) + (
        _esmc_method(),
    ),
    bindings=tuple(
        _binding(operation, model)
        for model in _MODELS
        for operation in _OPERATIONS
    ) + tuple(_local_binding(operation) for operation in _OPERATIONS) + (
        _esmc_binding(),
    ),
    port_types=(_port_types.ESMC_SEQUENCE_REPRESENTATION_PORT_TYPE,),
)
