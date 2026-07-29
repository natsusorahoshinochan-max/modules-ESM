"""The single production registration for remote ESM-3 generation."""

from __future__ import annotations

from collections.abc import Mapping
from functools import lru_cache
import importlib.util
from pathlib import Path
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
from core.provider_contract import (
    BIOHUB_ESM3_MODEL,
    ESM_SDK_REVISION,
    validate_biohub_token_file,
    validate_installed_provider_checkout,
)

from .implementation import ESM3GenerationImplementation


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


@lru_cache(maxsize=1)
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


def _ready(environment: object) -> bool:
    if not isinstance(environment, Mapping):
        return False
    if environment.get("endpoint_id") != "biohub":
        return False
    client = environment.get("provider_client")
    client_factory = environment.get("client_factory")
    if callable(getattr(client, "generate", None)) or callable(client_factory):
        return environment.get("credential_handle") is not None
    credential_file = environment.get("credential_file")
    if not isinstance(credential_file, (str, Path)):
        return False
    try:
        validate_biohub_token_file(credential_file)
    except (OSError, ValueError):
        return False
    return _provider_installation_is_exact()


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


def _build(operation: str):
    def factory(**kwargs: object) -> object:
        return ESM3GenerationImplementation(
            kwargs["run_resources"],
            operation,
            kwargs["environment_configuration"],
            kwargs["frozen_catalog"],
        )

    return factory


def _method(operation: str) -> MethodDefinition:
    provider_operation = {
        "generate_sequence": "generate(track=sequence)",
        "generate_structure": "generate(track=structure)",
        "generate_paired": (
            "generate(track=sequence) then generate(track=structure)"
        ),
    }[operation]
    return MethodDefinition(
        method_id=f"esm3.{operation}.esm3_medium_2024_08",
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
            "model": BIOHUB_ESM3_MODEL,
            "source": "Biohub",
            "scale": "medium",
            "release": "2024-08",
        },
        checkpoint_identity={
            "kind": "provider_managed_exact_model_id",
            "model": BIOHUB_ESM3_MODEL,
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
        "reconstructed_structure_candidates"
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
            guaranteed_multiplicity="one",
            output_partition="structure_confidence",
        )
    )
    return tuple(observations)


def _binding(operation: str) -> ExecutionBindingDefinition:
    return ExecutionBindingDefinition(
        binding_id=f"esm3.{operation}.biohub_medium",
        version=_VERSION,
        node_type=ContractIdentity(
            "node_type",
            f"esm3.{operation}",
            _VERSION,
        ),
        method=ContractIdentity(
            "method",
            f"esm3.{operation}.esm3_medium_2024_08",
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
                    "model": BIOHUB_ESM3_MODEL,
                },
            ),
            build=_build(operation),
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
            "model": BIOHUB_ESM3_MODEL,
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
    methods=tuple(_method(operation) for operation in _OPERATIONS),
    bindings=tuple(_binding(operation) for operation in _OPERATIONS),
)

