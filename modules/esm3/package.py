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
from core.catalog.port_contract import (
    BehaviorReference,
    PortTypeDefinition,
)
from core.operation import (
    AdmittedPort,
    BindingEnvironment,
    OperationContext,
    ReadinessResult,
    ScientificOperation,
)
from core.provider_support import (
    ProviderInstallationUnavailable,
    validate_installed_provider_checkout,
)

from .adapter import (
    BIOHUB_ESM3_MEDIUM_MODEL,
    BIOHUB_ESM3_OPEN_MODEL,
    BiohubESM3Adapter,
    ESM_SDK_REVISION,
)
from .implementation import ESM3GenerationOperation
from .esmc_implementation import ESMCRepresentationOperation
from .domain import (
    ESMC_MEAN_EMBEDDING_DIMENSION,
    ESMC_SEQUENCE_LOGITS_DIMENSION,
    ESMCSequenceRepresentation,
)
from .esmc_adapter import (
    BIOHUB_ESMC_MODEL,
    BiohubESMCAdapter,
    environment_ready as esmc_environment_ready,
)
from .local_adapter import (
    LOCAL_ESM3_DEVICE,
    LOCAL_ESM3_MODEL,
    LOCAL_ESM3_PERFORMANCE_SETTINGS,
    LOCAL_ESM3_SNAPSHOT_REVISION,
    LOCAL_ESM3_SNAPSHOT_SOURCE,
    LOCAL_ESM3_TORCH_VERSION,
    LOCAL_ESM3_WEIGHT_SHA256,
    LocalESM3Adapter,
    local_readiness,
    local_runtime_structurally_available,
)


_PACKAGE_VERSION = "6.0.0"
_GENERATION_METHOD_VERSION = "5.0.0"
_GENERATION_NODE_BINDING_VERSION = "8.0.0"
_ESMC_METHOD_VERSION = "3.0.0"
_ESMC_PORT_VERSION = "4.0.0"
_ESMC_NODE_BINDING_VERSION = "5.0.0"
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
    EnvironmentFieldDeclaration("endpoint_id", "json_value"),
    EnvironmentFieldDeclaration("credential_handle", "credential_handle"),
)
_LOCAL_ENVIRONMENT_FIELDS = (
    EnvironmentFieldDeclaration("model_snapshot_revision", "json_value"),
    EnvironmentFieldDeclaration("model_snapshot_path", "filesystem_path"),
    EnvironmentFieldDeclaration("runtime_directory", "filesystem_path"),
    EnvironmentFieldDeclaration("device", "json_value"),
    EnvironmentFieldDeclaration("performance_settings", "json_value"),
)


def _provider_installation_is_exact() -> bool:
    if importlib.util.find_spec("esm") is None:
        return False
    try:
        validate_installed_provider_checkout("esm", ESM_SDK_REVISION)
    except ProviderInstallationUnavailable:
        return False
    return True


def _provider_runtime_structurally_available() -> bool:
    return importlib.util.find_spec("esm") is not None


def _esmc_ready(check_input: BindingEnvironment) -> ReadinessResult:
    return ReadinessResult(
        esmc_environment_ready(check_input.values)
        and _provider_installation_is_exact()
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
        version=_ESMC_METHOD_VERSION,
        algorithm_identity={
            "name": "ESMC masked-language-model sequence representation",
            "provider_operations": ("encode", "logits"),
            "logits_request": {
                "sequence": True,
                "return_mean_embedding": True,
            },
            "published_value": (
                "locked-SDK-normalized mean embedding and sequence-logits "
                "shape on the CLS, residue-token, EOS axis"
            ),
        },
        model_identity={
            "model": BIOHUB_ESMC_MODEL,
            "source": "Biohub",
            "scale": "600M",
            "release": "2024-12",
        },
        checkpoint_identity={
            "kind": "provider_managed_exact_model_id",
            "model": BIOHUB_ESMC_MODEL,
        },
        featurization_identity={
            "input": "ESMProtein complete sequence",
            "tokenization": "Biohub ESMC encode endpoint",
            "residue_axis": "input order preserved",
        },
        source_identity={
            "sdk": "esm",
            "sdk_source_revision": ESM_SDK_REVISION,
            "service": "Biohub",
            "api_contract": "encode+logits@2026-07-16",
        },
        scale_contract={
            "mean_embedding": {
                "storage": "locked_sdk_normalized_binary32",
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
        version=_ESMC_NODE_BINDING_VERSION,
        node_type=ContractIdentity(
            "node_type",
            "esm3.represent_sequence",
            _ESMC_NODE_BINDING_VERSION,
        ),
        method=ContractIdentity(
            "method",
            "esm3.represent_sequence.esmc_600m_2024_12",
            _ESMC_METHOD_VERSION,
        ),
        binding_parameters={},
        environment_fields=_BIOHUB_ENVIRONMENT_FIELDS,
        execution_route="adapter",
        factory=ScientificOperationFactory(
            behavior=BehaviorReference(
                "esm3.represent_sequence/factory",
                _ESMC_NODE_BINDING_VERSION,
                {
                    "route": "biohub",
                    "model": BIOHUB_ESMC_MODEL,
                    "engine_identity": "exact_method_contract_digest",
                },
            ),
            build=_build_esmc,
        ),
        adapter_behavior=BehaviorReference(
            "esm3.biohub_esmc/adapter",
            _ESMC_NODE_BINDING_VERSION,
            {
                "provider_contract": "esm-sdk-encode+logits@917af90b",
                "output_contract": "mean-embedding-1152+logits-L+2x64",
                "engine_identity": "exact_method_contract_digest",
            },
        ),
        availability=AvailabilityDeclaration(
            behavior=BehaviorReference(
                "esm3.biohub_esmc/availability",
                _ESMC_NODE_BINDING_VERSION,
                {"observation": "startup"},
            ),
            prerequisites={
                "provider_sdk": {
                    "name": "esm",
                    "source_revision": ESM_SDK_REVISION,
                }
            },
            check=_available,
        ),
        readiness=ReadinessDeclaration(
            behavior=BehaviorReference(
                "esm3.biohub_esmc/readiness",
                _ESMC_NODE_BINDING_VERSION,
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
                "endpoint": {
                    "endpoint_id": "biohub",
                    "source": "trusted_environment_configuration",
                },
                "provider_sdk": {
                    "name": "esm",
                    "source_revision": ESM_SDK_REVISION,
                },
            },
            check=_esmc_ready,
        ),
        deterministic=True,
        cacheable=True,
        implementation_identity={
            "name": "esm3.represent_sequence.biohub-esmc-adapter",
            "model": BIOHUB_ESMC_MODEL,
            "source": "Biohub",
            "provider_operations": ("encode", "logits"),
            "output_contract": (
                "locked-SDK-normalized mean embedding with 1152 values plus "
                "exact (L + 2, 64) sequence-logits shape on the encoded "
                "token axis"
            ),
        },
    )


def _validate_esmc_representation(value: object) -> None:
    if type(value) is not ESMCSequenceRepresentation:
        raise ValueError("ESMC representation has the wrong runtime type")


def _esmc_representation_to_wire(value: object) -> object:
    assert isinstance(value, ESMCSequenceRepresentation)
    return {
        "sequence": value.sequence,
        "residue_ids": (
            None if value.residue_ids is None else list(value.residue_ids)
        ),
        "mean_embedding": list(value.mean_embedding),
        "sequence_logits_shape": list(value.sequence_logits_shape),
    }


def _esmc_representation_from_wire(value: object) -> object:
    if not isinstance(value, dict) or set(value) != {
        "sequence",
        "residue_ids",
        "mean_embedding",
        "sequence_logits_shape",
    }:
        raise ValueError("ESMC representation wire value is not closed")
    residue_ids = value["residue_ids"]
    mean_embedding = value["mean_embedding"]
    logits_shape = value["sequence_logits_shape"]
    if (
        (residue_ids is not None and not isinstance(residue_ids, list))
        or not isinstance(mean_embedding, list)
        or not isinstance(logits_shape, list)
    ):
        raise ValueError("ESMC representation wire value has invalid fields")
    if any(type(item) not in {int, float} for item in mean_embedding):
        raise ValueError("ESMC representation embedding is not numeric")
    return ESMCSequenceRepresentation(
        sequence=value["sequence"],
        residue_ids=(
            None if residue_ids is None else tuple(residue_ids)
        ),
        mean_embedding=tuple(float(item) for item in mean_embedding),
        sequence_logits_shape=tuple(logits_shape),
    )


def _esmc_port_type() -> PortTypeDefinition:
    type_id = "esm3.esmc_sequence_representation"
    return PortTypeDefinition(
        type_id=type_id,
        version=_ESMC_PORT_VERSION,
        validator=BehaviorReference(
            f"{type_id}/validate",
            _ESMC_PORT_VERSION,
            {
                "accepted_value_kind": "esmc_sequence_representation",
                "finite_binary32_embedding": True,
                "mean_embedding_dimension": ESMC_MEAN_EMBEDDING_DIMENSION,
                "sequence_logits_shape": "L_plus_2_by_64",
                "sequence_logits_axis": "CLS_residue_tokens_EOS",
                "sequence_logits_class_width": (
                    ESMC_SEQUENCE_LOGITS_DIMENSION
                ),
            },
        ),
        codec=BehaviorReference(
            f"{type_id}/codec",
            _ESMC_PORT_VERSION,
            {
                "canonicalization": "RFC 8785",
                "character_encoding": "UTF-8",
            },
        ),
        content_identity=BehaviorReference(
            f"{type_id}/content",
            _ESMC_PORT_VERSION,
            {"digest": "SHA-256"},
        ),
        runtime_validator=_validate_esmc_representation,
        runtime_to_wire=_esmc_representation_to_wire,
        runtime_from_wire=_esmc_representation_from_wire,
    )


def _available() -> AvailabilityResult:
    if _provider_runtime_structurally_available():
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
            "The exact local ESM SDK and Torch runtime prerequisites are "
            "unavailable."
        ),
        retryable=False,
    )


def _ready(check_input: BindingEnvironment) -> ReadinessResult:
    environment = check_input.values
    return ReadinessResult(
        environment["endpoint_id"] == "biohub"
        and _provider_installation_is_exact()
    )


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
        version=_GENERATION_METHOD_VERSION,
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
        checkpoint_identity={
            "kind": "provider_managed_exact_model_id",
            "model": model["model"],
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
        source_identity={
            "sdk": "esm",
            "sdk_source_revision": ESM_SDK_REVISION,
            "service": "Biohub",
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
        version=_GENERATION_METHOD_VERSION,
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
        checkpoint_identity={
            "kind": "immutable_huggingface_snapshot",
            "source": LOCAL_ESM3_SNAPSHOT_SOURCE,
            "snapshot_revision": LOCAL_ESM3_SNAPSHOT_REVISION,
            "weight_sha256": dict(sorted(LOCAL_ESM3_WEIGHT_SHA256.items())),
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
        source_identity={
            "sdk": "esm",
            "sdk_source_revision": ESM_SDK_REVISION,
            "service": "local_open",
            "snapshot_source": LOCAL_ESM3_SNAPSHOT_SOURCE,
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
        version=_GENERATION_NODE_BINDING_VERSION,
        node_type=ContractIdentity(
            "node_type",
            f"esm3.{operation}",
            _GENERATION_NODE_BINDING_VERSION,
        ),
        method=ContractIdentity(
            "method",
            method_id,
            _GENERATION_METHOD_VERSION,
        ),
        binding_parameters={},
        environment_fields=_BIOHUB_ENVIRONMENT_FIELDS,
        execution_route="adapter",
        factory=ScientificOperationFactory(
            behavior=BehaviorReference(
                f"esm3.{operation}/factory",
                _GENERATION_NODE_BINDING_VERSION,
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
            _GENERATION_NODE_BINDING_VERSION,
            {
                "provider_contract": "esm-sdk-generate@917af90b",
                "track_translation": "documented-provider-output",
                "engine_identity": "exact_method_contract_digest",
                "randomness_evidence": "provider_uncontrolled",
            },
        ),
        availability=AvailabilityDeclaration(
            behavior=BehaviorReference(
                "esm3.biohub/availability",
                _GENERATION_NODE_BINDING_VERSION,
                {"observation": "startup"},
            ),
            prerequisites={
                "provider_sdk": {
                    "name": "esm",
                    "source_revision": ESM_SDK_REVISION,
                }
            },
            check=_available,
        ),
        readiness=ReadinessDeclaration(
            behavior=BehaviorReference(
                "esm3.biohub/readiness",
                _GENERATION_NODE_BINDING_VERSION,
                {
                    "observation": "cache-miss",
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
            check=_ready,
        ),
        deterministic=False,
        cacheable=False,
        implementation_identity={
            "name": f"esm3.{operation}.biohub-adapter",
            "model": model["model"],
            "source": "Biohub",
            "provider_seed_control": "unsupported_by_provider",
            "cache_policy": "uncontrolled_remote_generation_is_not_cacheable",
        },
    )


def _local_binding(operation: str) -> ExecutionBindingDefinition:
    method_id = f"esm3.{operation}.esm3_sm_open_v1_local"
    return ExecutionBindingDefinition(
        binding_id=f"esm3.{operation}.local_open",
        version=_GENERATION_NODE_BINDING_VERSION,
        node_type=ContractIdentity(
            "node_type",
            f"esm3.{operation}",
            _GENERATION_NODE_BINDING_VERSION,
        ),
        method=ContractIdentity(
            "method",
            method_id,
            _GENERATION_METHOD_VERSION,
        ),
        binding_parameters={},
        environment_fields=_LOCAL_ENVIRONMENT_FIELDS,
        execution_route="adapter",
        factory=ScientificOperationFactory(
            behavior=BehaviorReference(
                f"esm3.{operation}/factory",
                _GENERATION_NODE_BINDING_VERSION,
                {
                    "route": "local_open",
                    "model": LOCAL_ESM3_MODEL,
                    "snapshot_revision": LOCAL_ESM3_SNAPSHOT_REVISION,
                },
            ),
            build=_build_local(
                operation,
                model_name=LOCAL_ESM3_MODEL,
            ),
        ),
        adapter_behavior=BehaviorReference(
            "esm3.local_open/adapter",
            _GENERATION_NODE_BINDING_VERSION,
            {
                "provider_contract": (
                    "esm-sdk-local-generate@917af90b"
                ),
                "track_translation": "documented-provider-output",
                "engine_identity": "exact_method_contract_digest",
                "seed_control": (
                    "exact-torch-seed-from-input-content-and-sample-track-slot"
                ),
                "randomness_evidence": "exact_seed",
            },
        ),
        availability=AvailabilityDeclaration(
            behavior=BehaviorReference(
                "esm3.local_open/availability",
                _GENERATION_NODE_BINDING_VERSION,
                {
                    "observation": "startup",
                    "model_load": "forbidden",
                },
            ),
            prerequisites={
                "provider_sdk": {
                    "name": "esm",
                    "source_revision": ESM_SDK_REVISION,
                },
                "runtime": {
                    "name": "torch",
                    "version": LOCAL_ESM3_TORCH_VERSION,
                },
            },
            check=_local_available,
        ),
        readiness=ReadinessDeclaration(
            behavior=BehaviorReference(
                "esm3.local_open/readiness",
                _GENERATION_NODE_BINDING_VERSION,
                {
                    "observation": "cache-miss",
                    "secret_retention": "none",
                    "cache_order": "before-provider-entry",
                },
            ),
            prerequisites={
                "model_snapshot": {
                    "source": LOCAL_ESM3_SNAPSHOT_SOURCE,
                    "snapshot_revision": LOCAL_ESM3_SNAPSHOT_REVISION,
                    "weight_sha256": dict(
                        sorted(LOCAL_ESM3_WEIGHT_SHA256.items())
                    ),
                    "path_source": "trusted_environment_configuration",
                },
                "device": {
                    "source": "trusted_environment_configuration",
                    "exact_value": LOCAL_ESM3_DEVICE,
                },
                "runtime_directory": {
                    "source": "trusted_environment_configuration",
                },
                "performance_settings": {
                    "source": "trusted_environment_configuration",
                    "exact_value": dict(LOCAL_ESM3_PERFORMANCE_SETTINGS),
                },
                "provider_sdk": {
                    "name": "esm",
                    "source_revision": ESM_SDK_REVISION,
                },
            },
            check=_local_ready,
        ),
        deterministic=False,
        cacheable=False,
        implementation_identity={
            "name": f"esm3.{operation}.local-open-adapter",
            "model": LOCAL_ESM3_MODEL,
            "snapshot_revision": LOCAL_ESM3_SNAPSHOT_REVISION,
            "weight_sha256": dict(sorted(LOCAL_ESM3_WEIGHT_SHA256.items())),
            "source": LOCAL_ESM3_SNAPSHOT_SOURCE,
            "device": LOCAL_ESM3_DEVICE,
            "torch_version": LOCAL_ESM3_TORCH_VERSION,
            "performance_settings": dict(LOCAL_ESM3_PERFORMANCE_SETTINGS),
            "runtime_directory_policy": (
                "performance-only-binding-scoped-private"
            ),
            "seed_control": "torch_local",
            "determinism_contract": (
                "exact Torch seed derived from configured base seed, canonical "
                "ProteinPrompt content digest, and zero-based sample-track "
                "slot; no cross-device bitwise guarantee"
            ),
            "cache_policy": "runtime-device-specific_generation_not_cacheable",
        },
        effective_randomness_parameters=("effective_seed",),
        effective_randomness_resolver=EffectiveRandomnessResolver(
            behavior=BehaviorReference(
                "esm3.local/effective-randomness",
                _GENERATION_NODE_BINDING_VERSION,
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
    package_version=_PACKAGE_VERSION,
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
    port_types=(_esmc_port_type(),),
)
