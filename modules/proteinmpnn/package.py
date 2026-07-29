"""The single production registration for ProteinMPNN constraints and design."""

from __future__ import annotations

from collections.abc import Mapping
import importlib.metadata
import importlib.util
import math
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
    ReadinessDeclaration,
)
from core.provider_contract import (
    PROTEINMPNN_REVISION,
    PROTEINMPNN_V_48_020_SHA256,
)

from .v2_adapter import (
    PROTEINMPNN_CHECKPOINT,
    PROTEINMPNN_DEVICE,
    PROTEINMPNN_MODEL,
    PROTEINMPNN_TORCH_VERSION,
    proteinmpnn_readiness,
)
from .domain import normalize_design_parameters


_VERSION = "2.0.0"
_OPERATIONS = ("constraints", "random_fixed_positions", "design")


def _available() -> AvailabilityResult:
    return AvailabilityResult.available()


def _design_available() -> AvailabilityResult:
    if importlib.util.find_spec("torch") is not None:
        try:
            if (
                importlib.metadata.version("torch")
                == PROTEINMPNN_TORCH_VERSION
            ):
                return AvailabilityResult.available()
        except importlib.metadata.PackageNotFoundError:
            pass
    return AvailabilityResult.unavailable(
        code="proteinmpnn_runtime_unavailable",
        message="The exact ProteinMPNN Torch runtime is unavailable.",
        retryable=False,
    )


def _ready(environment: object) -> bool:
    del environment
    return True


def _build(operation: str):
    def factory(**kwargs: object) -> object:
        from .implementation import (
            ProteinMPNNConstraintsImplementation,
            ProteinMPNNDesignImplementation,
            ProteinMPNNRandomFixedPositionsImplementation,
        )

        implementation = {
            "constraints": ProteinMPNNConstraintsImplementation,
            "random_fixed_positions": (
                ProteinMPNNRandomFixedPositionsImplementation
            ),
            "design": ProteinMPNNDesignImplementation,
        }[operation]
        return implementation(
            kwargs["run_resources"],
            kwargs["environment_configuration"],
            kwargs["frozen_catalog"],
        )

    return factory


def _method(operation: str) -> MethodDefinition:
    if operation == "design":
        return MethodDefinition(
            method_id="proteinmpnn.design.v_48_020_8907e667",
            version=_VERSION,
            algorithm_identity={
                "name": "ProteinMPNN conditional sequence design",
                "sampling": "autoregressive decoding",
                "children_order": "parent-then-zero-based-sample",
                "constraint_indexing": (
                    "zero-based-workbench-to-one-based-chain-qualified-provider"
                ),
            },
            model_identity={
                "model": PROTEINMPNN_MODEL,
                "architecture": "ProteinMPNN",
                "source": "dauparas/ProteinMPNN",
            },
            checkpoint_identity={
                "relative_path": PROTEINMPNN_CHECKPOINT,
                "sha256": PROTEINMPNN_V_48_020_SHA256,
            },
            featurization_identity={
                "structure": "ProteinMPNN parse_PDB",
                "constraints": "ProteinMPNN tied_featurize",
                "reference_sequence": "exact-chain-layout",
            },
            source_identity={
                "repository": "dauparas/ProteinMPNN",
                "source_revision": PROTEINMPNN_REVISION,
            },
            scale_contract={
                "sequence": "canonical_20_amino_acids",
                "provider_score": (
                    "optional-native-negative-log-probability-validated-only"
                ),
            },
        )
    return MethodDefinition(
        method_id=f"proteinmpnn.{operation}.repository_owned",
        version=_VERSION,
        algorithm_identity={
            "name": (
                "validated-constraint-authoring"
                if operation == "constraints"
                else "sha256-ranked-fixed-position-selection"
            ),
            "indexing": "zero-based-explicit-residue-layout",
            "sampling": (
                "none"
                if operation == "constraints"
                else "without-replacement"
            ),
        },
        model_identity={"kind": "none"},
        checkpoint_identity={"kind": "none"},
        featurization_identity={
            "layout": "identity-complete-contiguous-chain-layout"
        },
        source_identity={"kind": "repository-owned"},
        scale_contract={"kind": "identity"},
    )


def _resolve_random_fixed_randomness(
    *,
    inputs: Mapping[str, Any],
    node_parameters: Mapping[str, Any],
    binding_parameters: Mapping[str, Any],
) -> dict[str, Any]:
    if set(inputs) != {"layout"} or binding_parameters:
        raise ValueError(
            "random fixed-position randomness requires one layout"
        )
    if set(node_parameters) != {"effective_seed", "fraction"}:
        raise ValueError(
            "random fixed-position parameters are not fully resolved"
        )
    seed = node_parameters["effective_seed"]
    fraction = node_parameters["fraction"]
    if type(seed) is not int or not 0 <= seed <= 9_007_199_254_740_991:
        raise ValueError("effective_seed is outside its contract")
    if (
        isinstance(fraction, bool)
        or not isinstance(fraction, (int, float))
        or not math.isfinite(float(fraction))
        or not 0 <= float(fraction) <= 1
    ):
        raise ValueError("fraction is outside its contract")
    return {"effective_seed": seed, "fraction": float(fraction)}


def _resolve_design_randomness(
    *,
    inputs: Mapping[str, Any],
    node_parameters: Mapping[str, Any],
    binding_parameters: Mapping[str, Any],
) -> dict[str, Any]:
    del inputs
    return normalize_design_parameters(
        node_parameters,
        binding_parameters,
    )


def _binding(operation: str) -> ExecutionBindingDefinition:
    is_design = operation == "design"
    randomness_parameters = (
        (
            "effective_seed",
            "num_sequences",
            "temperature",
            "backbone_noise",
        )
        if is_design
        else (
            ("effective_seed", "fraction")
            if operation == "random_fixed_positions"
            else ()
        )
    )
    method_id = (
        "proteinmpnn.design.v_48_020_8907e667"
        if is_design
        else f"proteinmpnn.{operation}.repository_owned"
    )
    return ExecutionBindingDefinition(
        binding_id=f"proteinmpnn.{operation}.local",
        version=_VERSION,
        node_type=ContractIdentity(
            "node_type",
            f"proteinmpnn.{operation}",
            _VERSION,
        ),
        method=ContractIdentity("method", method_id, _VERSION),
        binding_parameters={},
        execution_route="adapter" if is_design else "direct",
        factory=LazyImplementationFactory(
            behavior=BehaviorReference(
                f"proteinmpnn.{operation}/factory",
                _VERSION,
                {
                    "route": "local" if is_design else "repository-owned",
                    "model": PROTEINMPNN_MODEL if is_design else "none",
                },
            ),
            build=_build(operation),
        ),
        adapter_behavior=(
            BehaviorReference(
                "proteinmpnn.local/adapter",
                _VERSION,
                {
                    "provider_contract": (
                        f"dauparas/ProteinMPNN@{PROTEINMPNN_REVISION}"
                    ),
                    "model": PROTEINMPNN_MODEL,
                    "checkpoint_sha256": PROTEINMPNN_V_48_020_SHA256,
                    "device": PROTEINMPNN_DEVICE,
                },
            )
            if is_design
            else None
        ),
        availability=AvailabilityDeclaration(
            behavior=BehaviorReference(
                f"proteinmpnn.{operation}/availability",
                _VERSION,
                {
                    "observation": "startup",
                    "model_load": "forbidden",
                },
            ),
            prerequisites=(
                {
                    "provider_checkout": {
                        "source": "dauparas/ProteinMPNN",
                        "source_revision": PROTEINMPNN_REVISION,
                    },
                    "runtime": {
                        "name": "torch",
                        "version": PROTEINMPNN_TORCH_VERSION,
                    },
                }
                if is_design
                else {}
            ),
            check=_design_available if is_design else _available,
        ),
        readiness=ReadinessDeclaration(
            behavior=BehaviorReference(
                f"proteinmpnn.{operation}/readiness",
                _VERSION,
                {
                    "observation": "per-run",
                    "cache_order": "before-cache-lookup",
                    "model_load": "forbidden",
                    "secret_retention": "none",
                },
            ),
            prerequisites=(
                {
                    "provider_checkout": {
                        "source_revision": PROTEINMPNN_REVISION,
                        "path_source": "trusted_environment_configuration",
                    },
                    "model_checkpoint": {
                        "relative_path": PROTEINMPNN_CHECKPOINT,
                        "sha256": PROTEINMPNN_V_48_020_SHA256,
                        "path_source": "trusted_environment_configuration",
                    },
                    "device": {
                        "source": "trusted_environment_configuration",
                        "exact_value": PROTEINMPNN_DEVICE,
                    },
                    "runtime_fingerprint": {
                        "source": "trusted_environment_configuration",
                        "safe_public_identity": True,
                    },
                }
                if is_design
                else {}
            ),
            check=proteinmpnn_readiness if is_design else _ready,
        ),
        deterministic=True,
        cacheable=True,
        implementation_identity=(
            {
                "name": "proteinmpnn.design.local-adapter",
                "model": PROTEINMPNN_MODEL,
                "checkpoint": PROTEINMPNN_CHECKPOINT,
                "checkpoint_sha256": PROTEINMPNN_V_48_020_SHA256,
                "source_revision": PROTEINMPNN_REVISION,
                "device": PROTEINMPNN_DEVICE,
                "torch_version": PROTEINMPNN_TORCH_VERSION,
                "seed_control": "torch_local",
                "runtime_directory_policy": (
                    "private-per-parent-engine-invocation"
                ),
            }
            if is_design
            else {
                "name": f"proteinmpnn.{operation}.direct",
                "source": "repository-owned",
                "process_global_randomness": "forbidden",
            }
        ),
        effective_randomness_parameters=randomness_parameters,
        effective_randomness_resolver=(
            EffectiveRandomnessResolver(
                behavior=BehaviorReference(
                    f"proteinmpnn.{operation}/effective-randomness",
                    _VERSION,
                    {
                        "normalization": (
                            "resolved-values-and-explicit-layout-v1"
                        )
                    },
                ),
                resolve=(
                    _resolve_design_randomness
                    if is_design
                    else _resolve_random_fixed_randomness
                ),
            )
            if randomness_parameters
            else None
        ),
    )


MODULE_PACKAGE = ModulePackageRegistration(
    schema_version=_VERSION,
    package_id="proteinmpnn",
    package_version=_VERSION,
    package_module=__package__,
    node_definitions=(
        DefinitionResource("definitions/constraints.yaml"),
        DefinitionResource("definitions/random_fixed_positions.yaml"),
        DefinitionResource("definitions/design.yaml"),
    ),
    methods=tuple(_method(operation) for operation in _OPERATIONS),
    bindings=tuple(_binding(operation) for operation in _OPERATIONS),
)
