"""The single production registration for remote and local ESM-3 generation."""

from __future__ import annotations

from collections.abc import Mapping
import importlib.util
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
from modules.provider_contract import validate_installed_provider_checkout

from .adapter import (
    BIOHUB_ESM3_MEDIUM_MODEL,
    BIOHUB_ESM3_OPEN_MODEL,
    ESM_SDK_REVISION,
)
from .implementation import ESM3GenerationImplementation
from .local_adapter import (
    LOCAL_ESM3_DEVICE,
    LOCAL_ESM3_MODEL,
    LOCAL_ESM3_PERFORMANCE_SETTINGS,
    LOCAL_ESM3_SNAPSHOT_REVISION,
    LOCAL_ESM3_SNAPSHOT_SOURCE,
    LOCAL_ESM3_TORCH_VERSION,
    LOCAL_ESM3_WEIGHT_SHA256,
    local_readiness,
    local_runtime_structurally_available,
)


_VERSION = "2.0.0"
_OPERATIONS = (
    "generate_sequence",
    "generate_structure",
    "generate_paired",
)
_CONFIDENCE_METRICS = (
    "structure.ptm",
    "structure.plddt.per_residue",
    "structure.plddt.mean_residue",
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


def _provider_installation_is_exact() -> bool:
    if importlib.util.find_spec("esm") is None:
        return False
    try:
        validate_installed_provider_checkout("esm", ESM_SDK_REVISION)
    except (OSError, RuntimeError, ValueError):
        return False
    return True


def _available() -> AvailabilityResult:
    if _provider_installation_is_exact():
        return AvailabilityResult.available()
    return AvailabilityResult.unavailable(
        code="esm_sdk_unavailable",
        message="The exact locked ESM SDK installation is unavailable.",
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


def _ready(environment: object) -> bool:
    if not isinstance(environment, Mapping):
        return False
    if environment.get("endpoint_id") != "biohub":
        return False
    client = environment.get("provider_client")
    client_factory = environment.get("client_factory")
    has_bound_client = (
        callable(getattr(client, "generate", None))
        or callable(client_factory)
    )
    return (
        has_bound_client
        and environment.get("credential_handle") is not None
        and _provider_installation_is_exact()
    )


def _resolve_effective_randomness(
    *,
    inputs: Mapping[str, Any],
    node_parameters: Mapping[str, Any],
    binding_parameters: Mapping[str, Any],
) -> dict[str, Any]:
    del inputs
    if binding_parameters:
        raise ValueError("remote ESM-3 Bindings accept no route parameters")
    seed = node_parameters.get("effective_seed")
    if (
        type(seed) is not int
        or seed < 0
        or seed > 9_007_199_254_740_991
    ):
        raise ValueError("effective_seed must be one resolved I-JSON integer")
    return {"effective_seed": seed}


def _build(
    operation: str,
    *,
    model_name: str,
    method_id: str,
):
    def factory(**kwargs: object) -> object:
        return ESM3GenerationImplementation(
            kwargs["run_resources"],
            operation,
            kwargs["environment_configuration"],
            kwargs["frozen_catalog"],
            model_name=model_name,
            method_id=method_id,
        )

    return factory


def _build_local(
    operation: str,
    *,
    model_name: str,
    method_id: str,
):
    def factory(**kwargs: object) -> object:
        return ESM3GenerationImplementation(
            kwargs["run_resources"],
            operation,
            kwargs["environment_configuration"],
            kwargs["frozen_catalog"],
            model_name=model_name,
            method_id=method_id,
            route_name="local_open",
            seed_control="torch_local",
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
        version=_VERSION,
        algorithm_identity={
            "name": "ESM-3 iterative masked-track generation",
            "operation": provider_operation,
            "condition_on_coordinates_only": True,
            "pairing": (
                "one terminal sequence to one structure counterpart"
                if operation == "generate_paired"
                else "not_applicable"
            ),
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


def _produced_observations(
    operation: str,
) -> tuple[ProducedObservationDefinition, ...]:
    subject_port = (
        "sequence_reconstruction_candidates"
        if operation == "generate_sequence"
        else "structure_candidates"
    )
    observations = [
        ProducedObservationDefinition(
            output_port="confidence_observations",
            metric=ContractIdentity("metric", metric, _VERSION),
            context_profile={"kind": "intrinsic"},
            subject_grain="candidate",
            source_role="subject",
            subject_direction="output",
            subject_port=subject_port,
            guaranteed_multiplicity="one",
            output_partition="structure_confidence",
        )
        for metric in _CONFIDENCE_METRICS
    ]
    observations.append(
        ProducedObservationDefinition(
            output_port="pae_observations",
            metric=ContractIdentity("metric", "structure.pae", _VERSION),
            context_profile={"kind": "intrinsic"},
            subject_grain="candidate",
            source_role="subject",
            subject_direction="output",
            subject_port=subject_port,
            guaranteed_multiplicity="zero_or_more",
            output_partition="structure_confidence",
        )
    )
    if operation == "generate_paired":
        observations.extend(
            ProducedObservationDefinition(
                output_port="sequence_reconstruction_confidence_observations",
                metric=ContractIdentity("metric", metric, _VERSION),
                context_profile={"kind": "intrinsic"},
                subject_grain="candidate",
                source_role="subject",
                subject_direction="output",
                subject_port="sequence_reconstruction_candidates",
                guaranteed_multiplicity="one",
                output_partition="sequence_reconstruction_confidence",
            )
            for metric in _CONFIDENCE_METRICS
        )
        observations.append(
            ProducedObservationDefinition(
                output_port="sequence_reconstruction_pae_observations",
                metric=ContractIdentity(
                    "metric",
                    "structure.pae",
                    _VERSION,
                ),
                context_profile={"kind": "intrinsic"},
                subject_grain="candidate",
                source_role="subject",
                subject_direction="output",
                subject_port="sequence_reconstruction_candidates",
                guaranteed_multiplicity="zero_or_more",
                output_partition="sequence_reconstruction_confidence",
            )
        )
    return tuple(observations)


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
        version=_VERSION,
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
                "derived Torch seed per sample and track; exact outputs are "
                "runtime-device-specific and are not cacheable"
            ),
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
        },
    )


def _binding(
    operation: str,
    model: Mapping[str, str],
) -> ExecutionBindingDefinition:
    method_id = f"esm3.{operation}.esm3_{model['suffix']}"
    return ExecutionBindingDefinition(
        binding_id=f"esm3.{operation}.{model['route']}",
        version=_VERSION,
        node_type=ContractIdentity(
            "node_type",
            f"esm3.{operation}",
            _VERSION,
        ),
        method=ContractIdentity(
            "method",
            method_id,
            _VERSION,
        ),
        binding_parameters={},
        execution_route="adapter",
        factory=LazyImplementationFactory(
            behavior=BehaviorReference(
                f"esm3.{operation}/factory",
                _VERSION,
                {
                    "route": "biohub",
                    "model": model["model"],
                },
            ),
            build=_build(
                operation,
                model_name=model["model"],
                method_id=method_id,
            ),
        ),
        adapter_behavior=BehaviorReference(
            "esm3.biohub/adapter",
            _VERSION,
            {
                "provider_contract": "esm-sdk-generate@917af90b",
                "track_fidelity": "fail-closed-no-silent-field-discard",
            },
        ),
        availability=AvailabilityDeclaration(
            behavior=BehaviorReference(
                "esm3.biohub/availability",
                _VERSION,
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
                _VERSION,
                {
                    "observation": "per-run",
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
        produced_observations=_produced_observations(operation),
        effective_randomness_parameters=("effective_seed",),
        effective_randomness_resolver=EffectiveRandomnessResolver(
            behavior=BehaviorReference(
                "esm3.remote/effective-randomness",
                _VERSION,
                {
                    "provider_seed_control": "unsupported_by_provider",
                    "sample_order": "zero-based",
                },
            ),
            resolve=_resolve_effective_randomness,
        ),
    )


def _local_binding(operation: str) -> ExecutionBindingDefinition:
    method_id = f"esm3.{operation}.esm3_sm_open_v1_local"
    return ExecutionBindingDefinition(
        binding_id=f"esm3.{operation}.local_open",
        version=_VERSION,
        node_type=ContractIdentity(
            "node_type",
            f"esm3.{operation}",
            _VERSION,
        ),
        method=ContractIdentity("method", method_id, _VERSION),
        binding_parameters={},
        execution_route="adapter",
        factory=LazyImplementationFactory(
            behavior=BehaviorReference(
                f"esm3.{operation}/factory",
                _VERSION,
                {
                    "route": "local_open",
                    "model": LOCAL_ESM3_MODEL,
                    "snapshot_revision": LOCAL_ESM3_SNAPSHOT_REVISION,
                },
            ),
            build=_build_local(
                operation,
                model_name=LOCAL_ESM3_MODEL,
                method_id=method_id,
            ),
        ),
        adapter_behavior=BehaviorReference(
            "esm3.local_open/adapter",
            _VERSION,
            {
                "provider_contract": (
                    "esm-sdk-local-generate@917af90b"
                ),
                "track_fidelity": "fail-closed-no-silent-field-discard",
                "seed_control": "derived-torch-seed-per-sample-track",
            },
        ),
        availability=AvailabilityDeclaration(
            behavior=BehaviorReference(
                "esm3.local_open/availability",
                _VERSION,
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
                _VERSION,
                {
                    "observation": "per-run",
                    "secret_retention": "none",
                    "cache_order": "before-cache-lookup",
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
                "runtime_fingerprint": {
                    "source": "trusted_environment_configuration",
                    "safe_public_identity": True,
                },
                "provider_sdk": {
                    "name": "esm",
                    "source_revision": ESM_SDK_REVISION,
                },
            },
            check=local_readiness,
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
                "derived Torch seed per sample and track; no cross-device "
                "bitwise guarantee"
            ),
            "cache_policy": "runtime-device-specific_generation_not_cacheable",
        },
        produced_observations=_produced_observations(operation),
        effective_randomness_parameters=("effective_seed",),
        effective_randomness_resolver=EffectiveRandomnessResolver(
            behavior=BehaviorReference(
                "esm3.local/effective-randomness",
                _VERSION,
                {
                    "provider_seed_control": "torch_local",
                    "sample_order": "zero-based",
                    "track_scope": "sample-and-track",
                },
            ),
            resolve=_resolve_effective_randomness,
        ),
    )


MODULE_PACKAGE = ModulePackageRegistration(
    schema_version=_VERSION,
    package_id="esm3",
    package_version=_VERSION,
    package_module=__package__,
    node_definitions=(
        DefinitionResource("definitions/generate_sequence.yaml"),
        DefinitionResource("definitions/generate_structure.yaml"),
        DefinitionResource("definitions/generate_paired.yaml"),
    ),
    metric_definitions=(
        DefinitionResource("definitions/plddt_per_residue_metric.yaml"),
        DefinitionResource("definitions/plddt_mean_residue_metric.yaml"),
        DefinitionResource("definitions/ptm_metric.yaml"),
        DefinitionResource("definitions/pae_metric.yaml"),
    ),
    methods=tuple(
        _method(operation, model)
        for model in _MODELS
        for operation in _OPERATIONS
    ) + tuple(_local_method(operation) for operation in _OPERATIONS),
    bindings=tuple(
        _binding(operation, model)
        for model in _MODELS
        for operation in _OPERATIONS
    ) + tuple(_local_binding(operation) for operation in _OPERATIONS),
)
