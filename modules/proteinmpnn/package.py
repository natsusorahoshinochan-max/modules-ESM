"""The single production registration for ProteinMPNN constraints and design."""

from __future__ import annotations

from collections.abc import Callable, Mapping
import importlib.util
from typing import Any, cast

from core.catalog.declarations import (
    AvailabilityDeclaration,
    AvailabilityResult,
    ContractIdentity,
    EffectiveRandomnessResolver,
    EnvironmentFieldDeclaration,
    ExecutionBindingDefinition,
    MethodDefinition,
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
    PortTypeDefinition,
)
from core.operation import (
    AdmittedPort,
    OperationContext,
    ReadinessCheckInput,
    ReadinessResult,
    ScientificOperation,
)
from modules.proteinmpnn.domain import ProteinMPNNConstraints
from datatypes.i_json import thaw_i_json
from datatypes.residue import ResidueLayout
from modules.proteinmpnn.assets import (
    PROTEINMPNN_REVISION,
    PROTEINMPNN_V_48_020_SHA256,
)

from .adapter import (
    LocalProteinMPNNAdapter,
    PROTEINMPNN_CHECKPOINT,
    PROTEINMPNN_DEVICE,
    PROTEINMPNN_MODEL,
    PROTEINMPNN_TORCH_VERSION,
    proteinmpnn_readiness,
)
from .domain import (
    validate_constraints_against_layout,
)


_PACKAGE_VERSION = "7.0.0"
_CONSTRAINTS_VERSION = "4.0.0"
_SCORE_METRIC_VERSION = "3.0.0"
_OPERATIONS = ("constraints", "random_fixed_positions", "design", "score")
_NODE_VERSIONS = {
    "constraints": "4.0.0",
    "random_fixed_positions": "4.0.0",
    "design": "10.0.0",
    "score": "7.0.0",
}
_BINDING_VERSIONS = {
    "constraints": "4.0.0",
    "random_fixed_positions": "4.0.0",
    "design": "11.0.0",
    "score": "8.0.0",
}
_METHOD_VERSIONS = {
    "constraints": "3.0.0",
    "random_fixed_positions": "3.0.0",
    "design": "6.0.0",
    "score": "6.0.0",
}


def _validate_constraints(value: object) -> None:
    if type(value) is not ProteinMPNNConstraints:
        raise ValueError("constraints must use the exact ProteinMPNN contract")
    validate_constraints_against_layout(value, layout=value.layout)


def _constraints_to_wire(value: object) -> dict[str, object]:
    value = cast(ProteinMPNNConstraints, value)
    return thaw_i_json({
        "layout": {
            "chain_id": value.layout.chain_id,
            "length": value.layout.length,
            "residue_ids": value.layout.residue_ids,
        },
        "designable_residue_ids": value.designable_residue_ids,
        "fixed_residue_ids": value.fixed_residue_ids,
        "designed_chains": value.designed_chains,
        "fixed_chains": value.fixed_chains,
        "omit_amino_acids": value.omit_amino_acids,
        "tied_residue_groups": value.tied_residue_groups,
        "bias_by_residue": (
            None
            if value.bias_by_residue is None
            else [
                [residue_id, dict(sorted(biases.items()))]
                for residue_id, biases in sorted(
                    value.bias_by_residue.items()
                )
            ]
        ),
    })


def _constraints_from_wire(value: object) -> ProteinMPNNConstraints:
    if not isinstance(value, dict) or set(value) != {
        "layout",
        "designable_residue_ids",
        "fixed_residue_ids",
        "designed_chains",
        "fixed_chains",
        "omit_amino_acids",
        "tied_residue_groups",
        "bias_by_residue",
    }:
        raise ValueError("ProteinMPNN constraints wire value is not closed")
    raw_biases = value["bias_by_residue"]
    if raw_biases is None:
        biases = None
    elif isinstance(raw_biases, list):
        biases = {}
        previous_residue_id: str | None = None
        for entry in raw_biases:
            if (
                not isinstance(entry, list)
                or len(entry) != 2
                or type(entry[0]) is not str
                or not isinstance(entry[1], dict)
                or entry[0] in biases
            ):
                raise ValueError(
                    "ProteinMPNN constraint biases are malformed"
                )
            if (
                previous_residue_id is not None
                and entry[0] <= previous_residue_id
            ) or list(entry[1]) != sorted(entry[1]):
                raise ValueError(
                    "ProteinMPNN constraint biases require canonical key order"
                )
            biases[entry[0]] = entry[1]
            previous_residue_id = entry[0]
    else:
        raise ValueError("ProteinMPNN constraint biases are malformed")
    raw_layout = value["layout"]
    if (
        not isinstance(raw_layout, dict)
        or set(raw_layout) != {"chain_id", "length", "residue_ids"}
    ):
        raise ValueError("ProteinMPNN constraint layout is malformed")

    layout = ResidueLayout(
        chain_id=raw_layout["chain_id"],
        length=raw_layout["length"],
        residue_ids=raw_layout["residue_ids"],
    )
    constraints = ProteinMPNNConstraints(
        layout=layout,
        designable_residue_ids=value["designable_residue_ids"],
        fixed_residue_ids=value["fixed_residue_ids"],
        designed_chains=value["designed_chains"],
        fixed_chains=value["fixed_chains"],
        omit_amino_acids=value["omit_amino_acids"],
        tied_residue_groups=value["tied_residue_groups"],
        bias_by_residue=biases,
    )
    return constraints


def _constraints_port_type() -> PortTypeDefinition:
    behavior_prefix = (
        "protein-workbench.port-type/proteinmpnn.constraints"
    )
    return PortTypeDefinition(
        type_id="proteinmpnn.constraints",
        version=_CONSTRAINTS_VERSION,
        validator=BehaviorReference(
            behavior_id=f"{behavior_prefix}/validate",
            behavior_version=_CONSTRAINTS_VERSION,
            parameters={
                "accepted_value_kind": "proteinmpnn_constraints",
                "complete_values_only": True,
            },
        ),
        codec=BehaviorReference(
            behavior_id=f"{behavior_prefix}/canonical-json-codec",
            behavior_version=_CONSTRAINTS_VERSION,
            parameters={
                "canonicalization": "RFC 8785",
                "character_encoding": "UTF-8",
                "envelope_namespace": "protein-workbench-port-value/v2",
                "value_kind": "proteinmpnn_constraints",
                "embedded_layout_contract": "residue.layout@3.0.0",
            },
        ),
        content_identity=BehaviorReference(
            behavior_id=f"{behavior_prefix}/content-sha256",
            behavior_version=_CONSTRAINTS_VERSION,
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
        return AvailabilityResult.available()
    return AvailabilityResult.unavailable(
        code="proteinmpnn_runtime_unavailable",
        message="The ProteinMPNN Torch runtime is unavailable.",
        retryable=False,
    )


def _model_ready(check_input: ReadinessCheckInput) -> ReadinessResult:
    return proteinmpnn_readiness(check_input.values)


def _build(
    operation: str,
) -> Callable[[OperationContext], ScientificOperation]:
    def factory(context: OperationContext) -> ScientificOperation:
        from .implementation import (
            ProteinMPNNConstraintsImplementation,
            ProteinMPNNDesignImplementation,
            ProteinMPNNRandomFixedPositionsImplementation,
            ProteinMPNNScoreImplementation,
        )

        if operation == "constraints":
            return ProteinMPNNConstraintsImplementation(context.resources)
        if operation == "random_fixed_positions":
            return ProteinMPNNRandomFixedPositionsImplementation(
                context.resources
            )
        adapter = LocalProteinMPNNAdapter(
            environment=context.environment,
            resources=context.resources,
        )
        if operation == "design":
            return ProteinMPNNDesignImplementation(
                adapter=adapter,
            )
        observation = context.produced_observations[0]
        return ProteinMPNNScoreImplementation(
            adapter=adapter,
            method=context.method,
            metric=observation.metric,
        )

    return factory


def _method(operation: str) -> MethodDefinition:
    version = _METHOD_VERSIONS[operation]
    if operation == "score":
        return MethodDefinition(
            method_id="proteinmpnn.score.v_48_020_8907e667",
            version=version,
            algorithm_identity={
                "name": "ProteinMPNN conditional sequence scoring",
                "provider_operation": "score_sequence",
                "decoding_order": "fixed-local-torch-seed",
                "decoding_order_seed": 42,
                "seed_application": "after-resident-model-resolution",
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
                "structure": (
                    "resolved-axis deterministic N-CA-C-O provider PDB "
                    "then ProteinMPNN parse_PDB"
                ),
                "residue_projection": (
                    "resolved-axis-segment-to-provider-safe-chain;"
                    "canonical-identity-to-segment-local-continuous-"
                    "one-based-position"
                ),
                "missing_backbone": (
                    "axis-selected-coordinate-or-provider-NaN-mask"
                ),
                "sequence": "canonical-20-amino-acid exact target layout",
                "tensorization": (
                    "ProteinMPNN tied_featurize all chains designed"
                ),
                "mask": (
                    "provider mask multiplied by chain_M and chain_M_pos"
                ),
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
            version=version,
            algorithm_identity={
                "name": "ProteinMPNN conditional sequence design",
                "sampling": "autoregressive decoding",
                "children_order": "parent-then-zero-based-sample",
                "constraint_indexing": (
                    "canonical-residue-identity-to-provider-segment-chain-"
                    "and-segment-local-continuous-one-based-position"
                ),
                "call_seed": (
                    "sha256-effective-seed-parent-structure-content-parent-slot"
                ),
                "seed_application": "after-resident-model-resolution",
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
                "structure": (
                    "resolved-axis deterministic N-CA-C-O provider PDB "
                    "then ProteinMPNN parse_PDB"
                ),
                "residue_projection": (
                    "resolved-axis-segment-to-provider-safe-chain;"
                    "canonical-identity-to-segment-local-continuous-"
                    "one-based-position"
                ),
                "constraints": "ProteinMPNN tied_featurize",
                "reference_sequence": "exact-chain-layout",
                "sequence_decoding": "complete-parsed-target-layout",
                "incomplete_backbone": (
                    "axis-selected-coordinate-or-provider-NaN-mask;"
                    "fixed-residue-preserved-designable-residue-rejected"
                ),
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
        version=version,
        algorithm_identity={
            "name": (
                "validated-constraint-authoring"
                if operation == "constraints"
                else "sha256-ranked-fixed-position-selection"
            ),
            "indexing": "stable-identity-explicit-residue-layout",
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
    inputs: Mapping[str, AdmittedPort],
    node_parameters: Mapping[str, Any],
    binding_parameters: Mapping[str, Any],
) -> dict[str, Any]:
    del inputs, binding_parameters
    return {
        "effective_seed": node_parameters["effective_seed"],
        "fraction": node_parameters["fraction"],
    }


def _resolve_design_randomness(
    *,
    inputs: Mapping[str, AdmittedPort],
    node_parameters: Mapping[str, Any],
    binding_parameters: Mapping[str, Any],
) -> dict[str, Any]:
    del inputs, binding_parameters
    return {
        name: node_parameters[name]
        for name in (
            "effective_seed",
            "num_sequences",
            "temperature",
            "backbone_noise",
        )
    }


def _binding(operation: str) -> ExecutionBindingDefinition:
    version = _BINDING_VERSIONS[operation]
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
                output_partition="default",
                metric=ContractIdentity(
                    "metric",
                    "proteinmpnn.native_sequence_nll",
                    _SCORE_METRIC_VERSION,
                ),
                context_profile={"kind": "intrinsic"},
                subject_grain="candidate",
                source_role="subject",
                subject_direction="input",
                subject_port="sequence_candidates",
                axis_direction="input",
                axis_port="structure_residue_axes",
                guaranteed_multiplicity="one",
            ),
        )
        if operation == "score"
        else ()
    )
    return ExecutionBindingDefinition(
        binding_id=f"proteinmpnn.{operation}.local",
        version=version,
        node_type=ContractIdentity(
            "node_type",
            f"proteinmpnn.{operation}",
            _NODE_VERSIONS[operation],
        ),
        method=ContractIdentity(
            "method",
            method_id,
            _METHOD_VERSIONS[operation],
        ),
        binding_parameters={},
        environment_fields=(
            (
                EnvironmentFieldDeclaration("provider_root", "filesystem_path"),
                EnvironmentFieldDeclaration("device", "json_value"),
            )
            if is_model
            else ()
        ),
        execution_route="adapter" if is_model else "direct",
        factory=ScientificOperationFactory(
            behavior=BehaviorReference(
                f"proteinmpnn.{operation}/factory",
                version,
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
                version,
                {
                    "provider_contract": (
                        f"dauparas/ProteinMPNN@{PROTEINMPNN_REVISION}"
                    ),
                    "model": PROTEINMPNN_MODEL,
                    "checkpoint_sha256": PROTEINMPNN_V_48_020_SHA256,
                    "device": PROTEINMPNN_DEVICE,
                    "structure_projection": (
                        "resolved-axis-segment-provider-native-staging-v2"
                    ),
                    "seed_application": (
                        "after-resident-model-resolution"
                    ),
                },
            )
            if is_model
            else None
        ),
        availability=AvailabilityDeclaration(
            behavior=BehaviorReference(
                f"proteinmpnn.{operation}/availability",
                version,
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
        readiness=(
            ReadinessDeclaration(
                behavior=BehaviorReference(
                    f"proteinmpnn.{operation}/readiness",
                    version,
                    {
                        "observation": "cache-miss",
                        "cache_order": "before-provider-entry",
                        "model_load": "forbidden",
                        "secret_retention": "none",
                    },
                ),
                prerequisites={
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
                },
                check=_model_ready,
            )
            if is_model
            else None
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
                "seed_application": "after-resident-model-resolution",
                "scientific_call_seed": (
                    "effective-seed-plus-structure-content-plus-parent-slot"
                    if is_design
                    else "fixed-scoring-seed"
                ),
                "runtime_directory_policy": (
                    "private-per-parent-engine-invocation"
                    if is_design
                    else "private-per-score-engine-invocation"
                ),
                "structure_projection": (
                    "resolved-axis-segment-provider-native-staging-v2"
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
                    version,
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
    package_version=_PACKAGE_VERSION,
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
        DefinitionResource("definitions/native_residue_nll_metric.yaml"),
    ),
    methods=tuple(_method(operation) for operation in _OPERATIONS),
    bindings=tuple(_binding(operation) for operation in _OPERATIONS),
)
