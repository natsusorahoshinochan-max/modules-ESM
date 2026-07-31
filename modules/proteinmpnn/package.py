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
    PortTypeDefinition,
    ProducedObservationDefinition,
    ReadinessCheckInput,
    ReadinessDeclaration,
    ReadinessResult,
)
from modules.provider_contract import (
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
from .domain import normalize_design_parameters, validate_constraints_against_layout
from datatypes import ProteinMPNNConstraints


_VERSION = "2.1.0"
_OPERATIONS = ("constraints", "random_fixed_positions", "design", "score")


def _validate_constraints(value: object) -> None:
    if type(value) is not ProteinMPNNConstraints:
        raise ValueError("constraints must use the exact ProteinMPNN contract")
    validate_constraints_against_layout(value, layout=value.layout)


def _constraints_to_wire(value: object) -> dict[str, object]:
    _validate_constraints(value)
    assert type(value) is ProteinMPNNConstraints
    return {
        "layout": {
            "chain_id": value.layout.chain_id,
            "length": value.layout.length,
            "residue_ids": value.layout.residue_ids,
        },
        "designable_positions": value.designable_positions,
        "fixed_positions": value.fixed_positions,
        "designed_chains": value.designed_chains,
        "fixed_chains": value.fixed_chains,
        "omit_amino_acids": value.omit_amino_acids,
        "tied_positions": value.tied_positions,
        "bias_by_res": (
            None
            if value.bias_by_res is None
            else [
                [position, dict(sorted(biases.items()))]
                for position, biases in sorted(value.bias_by_res.items())
            ]
        ),
    }


def _constraints_from_wire(value: object) -> ProteinMPNNConstraints:
    if not isinstance(value, dict) or set(value) != {
        "layout",
        "designable_positions",
        "fixed_positions",
        "designed_chains",
        "fixed_chains",
        "omit_amino_acids",
        "tied_positions",
        "bias_by_res",
    }:
        raise ValueError("ProteinMPNN constraints wire value is not closed")
    raw_biases = value["bias_by_res"]
    if raw_biases is None:
        biases = None
    elif isinstance(raw_biases, list):
        biases = {}
        previous_position: int | None = None
        for entry in raw_biases:
            if (
                not isinstance(entry, list)
                or len(entry) != 2
                or type(entry[0]) is not int
                or not isinstance(entry[1], dict)
                or entry[0] in biases
            ):
                raise ValueError(
                    "ProteinMPNN constraint biases are malformed"
                )
            if (
                previous_position is not None
                and entry[0] <= previous_position
            ) or list(entry[1]) != sorted(entry[1]):
                raise ValueError(
                    "ProteinMPNN constraint biases require canonical key order"
                )
            biases[entry[0]] = entry[1]
            previous_position = entry[0]
    else:
        raise ValueError("ProteinMPNN constraint biases are malformed")
    raw_layout = value["layout"]
    if (
        not isinstance(raw_layout, dict)
        or set(raw_layout) != {"chain_id", "length", "residue_ids"}
    ):
        raise ValueError("ProteinMPNN constraint layout is malformed")
    from datatypes import ResidueLayout

    layout = ResidueLayout(
        chain_id=raw_layout["chain_id"],
        length=raw_layout["length"],
        residue_ids=raw_layout["residue_ids"],
    )
    constraints = ProteinMPNNConstraints(
        layout=layout,
        designable_positions=value["designable_positions"],
        fixed_positions=value["fixed_positions"],
        designed_chains=value["designed_chains"],
        fixed_chains=value["fixed_chains"],
        omit_amino_acids=value["omit_amino_acids"],
        tied_positions=value["tied_positions"],
        bias_by_res=biases,
    )
    _validate_constraints(constraints)
    return constraints


def _constraints_port_type() -> PortTypeDefinition:
    behavior_prefix = (
        "protein-workbench.port-type/proteinmpnn.constraints"
    )
    return PortTypeDefinition(
        type_id="proteinmpnn.constraints",
        version=_VERSION,
        validator=BehaviorReference(
            behavior_id=f"{behavior_prefix}/validate",
            behavior_version=_VERSION,
            parameters={
                "accepted_value_kind": "proteinmpnn_constraints",
                "complete_values_only": True,
            },
        ),
        codec=BehaviorReference(
            behavior_id=f"{behavior_prefix}/canonical-json-codec",
            behavior_version=_VERSION,
            parameters={
                "canonicalization": "RFC 8785",
                "character_encoding": "UTF-8",
                "envelope_namespace": "protein-workbench-port-value/v2",
                "value_kind": "proteinmpnn_constraints",
            },
        ),
        content_identity=BehaviorReference(
            behavior_id=f"{behavior_prefix}/content-sha256",
            behavior_version=_VERSION,
            parameters={
                "digest_algorithm": "SHA-256",
                "digest_input": "canonical_codec_bytes",
                "digest_representation": (
                    "sha256:<64 lowercase hexadecimal digits>"
                ),
            },
        ),
        runtime_validator=_validate_constraints,
        runtime_to_wire=_constraints_to_wire,
        runtime_from_wire=_constraints_from_wire,
    )


def _available() -> AvailabilityResult:
    return AvailabilityResult.available()


def _model_available() -> AvailabilityResult:
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


def _ready(check_input: ReadinessCheckInput) -> ReadinessResult:
    del check_input
    return ReadinessResult(True)


def _model_ready(check_input: ReadinessCheckInput) -> ReadinessResult:
    return proteinmpnn_readiness(check_input.values)


def _build(operation: str):
    def factory(**kwargs: object) -> object:
        from .implementation import (
            ProteinMPNNConstraintsImplementation,
            ProteinMPNNDesignImplementation,
            ProteinMPNNRandomFixedPositionsImplementation,
            ProteinMPNNScoreImplementation,
        )

        implementation = {
            "constraints": ProteinMPNNConstraintsImplementation,
            "random_fixed_positions": (
                ProteinMPNNRandomFixedPositionsImplementation
            ),
            "design": ProteinMPNNDesignImplementation,
            "score": ProteinMPNNScoreImplementation,
        }[operation]
        return implementation(
            kwargs["run_resources"],
            kwargs["environment_configuration"],
            kwargs["frozen_catalog"],
        )

    return factory


def _method(operation: str) -> MethodDefinition:
    if operation == "score":
        return MethodDefinition(
            method_id="proteinmpnn.score.v_48_020_8907e667",
            version=_VERSION,
            algorithm_identity={
                "name": "ProteinMPNN conditional sequence scoring",
                "provider_operation": "score_sequence",
                "decoding_order": "fixed-local-torch-seed",
                "decoding_order_seed": 42,
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
                "sequence": "canonical-20-amino-acid exact target layout",
                "tensorization": (
                    "ProteinMPNN tied_featurize all chains designed"
                ),
                "mask": "provider mask multiplied by chain_M",
                "reduction": "provider _scores masked mean",
                "decoding_order_seed": 42,
            },
            source_identity={
                "repository": "dauparas/ProteinMPNN",
                "source_revision": PROTEINMPNN_REVISION,
            },
            scale_contract={
                "value": (
                    "provider-native-binary32-masked-mean-negative-"
                    "log-likelihood"
                ),
                "unit": "nats_per_designed_residue",
                "normalization": "none",
                "clamping": "forbidden",
            },
        )
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
    is_model = operation in {"design", "score"}
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
    method_id = {
        "design": "proteinmpnn.design.v_48_020_8907e667",
        "score": "proteinmpnn.score.v_48_020_8907e667",
    }.get(operation, f"proteinmpnn.{operation}.repository_owned")
    produced_observations = (
        (
            ProducedObservationDefinition(
                output_port="scores",
                metric=ContractIdentity(
                    "metric",
                    "proteinmpnn.native_sequence_nll",
                    _VERSION,
                ),
                context_profile={"kind": "intrinsic"},
                subject_grain="candidate",
                source_role="subject",
                subject_direction="input",
                subject_port="sequence_candidates",
                guaranteed_multiplicity="one",
            ),
        )
        if operation == "score"
        else ()
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
        execution_route="adapter" if is_model else "direct",
        factory=LazyImplementationFactory(
            behavior=BehaviorReference(
                f"proteinmpnn.{operation}/factory",
                _VERSION,
                {
                    "route": "local" if is_model else "repository-owned",
                    "model": PROTEINMPNN_MODEL if is_model else "none",
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
            if is_model
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
                if is_model
                else {}
            ),
            check=_model_available if is_model else _available,
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
                if is_model
                else {}
            ),
            check=_model_ready if is_model else _ready,
        ),
        deterministic=True,
        cacheable=True,
        implementation_identity=(
            {
                "name": f"proteinmpnn.{operation}.local-adapter",
                "model": PROTEINMPNN_MODEL,
                "checkpoint": PROTEINMPNN_CHECKPOINT,
                "checkpoint_sha256": PROTEINMPNN_V_48_020_SHA256,
                "source_revision": PROTEINMPNN_REVISION,
                "device": PROTEINMPNN_DEVICE,
                "torch_version": PROTEINMPNN_TORCH_VERSION,
                "seed_control": (
                    "torch_local"
                    if is_design
                    else "fixed_scoring_seed_42"
                ),
                "runtime_directory_policy": (
                    "private-per-parent-engine-invocation"
                    if is_design
                    else "private-per-score-engine-invocation"
                ),
            }
            if is_model
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
        produced_observations=produced_observations,
    )


MODULE_PACKAGE = ModulePackageRegistration(
    schema_version="2.1.0",
    package_id="proteinmpnn",
    package_version=_VERSION,
    package_module=__package__,
    port_types=(_constraints_port_type(),),
    node_definitions=(
        DefinitionResource("definitions/constraints.yaml"),
        DefinitionResource("definitions/random_fixed_positions.yaml"),
        DefinitionResource("definitions/design.yaml"),
        DefinitionResource("definitions/score.yaml"),
    ),
    metric_definitions=(
        DefinitionResource("definitions/native_sequence_nll_metric.yaml"),
    ),
    methods=tuple(_method(operation) for operation in _OPERATIONS),
    bindings=tuple(_binding(operation) for operation in _OPERATIONS),
)
