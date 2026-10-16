"""The single production registration for ProteinMPNN constraints and design."""

from __future__ import annotations

from datatypes.observation import PairwiseContextProfile

from core.catalog.observation import ObservationPortSource

from collections.abc import Callable, Mapping
import importlib.util
from typing import Any

from core.catalog.adopted_sources import with_adopted_sources

from core.catalog.declarations import (
    AvailabilityDeclaration,
    AvailabilityResult,
    EffectiveRandomnessResolver,
    EnvironmentFieldDeclaration,
    ExecutionBindingDefinition,
    MethodDefinition,
    ModulePackageRegistration,
    ReadinessDeclaration,
    ScientificOperationFactory,
)
from datatypes.exact_reference import ExactContractReference
from core.catalog.observation import ProducedObservation
from core.catalog.definition_resource import (
    DefinitionResource,
)
from core.catalog.port_contract import BehaviorReference
from core.operation import (
    AdmittedPort,
    OperationContext,
    ScientificOperation,
)
from core.local_torch_device import LOCAL_TORCH_DEVICE_POLICY

from .adapter import (
    LocalProteinMPNNAdapter,
    PROTEINMPNN_MODEL,
    proteinmpnn_readiness,
)
from .assets import PROTEINMPNN_FIXED_ASSET_FILES
from . import port_types as _port_types


_OPERATIONS = ("constraints", "random_fixed_positions", "design", "score")


def _model_available() -> AvailabilityResult:
    if importlib.util.find_spec("torch") is not None:
        return AvailabilityResult.available()
    return AvailabilityResult.unavailable(
        code="proteinmpnn_runtime_unavailable",
        message="The ProteinMPNN Torch runtime is unavailable.",
        retryable=False,
    )


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
    if operation == "score":
        return MethodDefinition(
            method_id="proteinmpnn.score.v_48_020_8907e667",
            algorithm_identity={
                "name": "ProteinMPNN conditional sequence scoring",
                "provider_operation": "score_sequence",
                "decoding_order": "explicit-local-torch-seed",
                "decoding_order_seed": "effective_seed",
                "seed_application": "after-resident-model-resolution",
            },
            model_identity={
                "model": PROTEINMPNN_MODEL,
                "architecture": "ProteinMPNN",
                "source": "dauparas/ProteinMPNN",
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
                "sequence": "standard-20-amino-acids-plus-X; matching identities or explicit complete sequence-position-to-backbone-residue correspondence",
                "tensorization": (
                    "ProteinMPNN tied_featurize all chains designed"
                ),
                "mask": (
                    "provider mask multiplied by chain_M and chain_M_pos"
                ),
                "reduction": "provider _scores masked mean",
                "decoding_order_seed": "effective_seed",
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
            method_id="proteinmpnn.design.v_48_020_8907e667_per_sample",
            algorithm_identity={
                "name": "ProteinMPNN conditional sequence design",
                "sampling": "autoregressive decoding",
                "children_order": "parent-then-zero-based-sample",
                "constraint_indexing": (
                    "canonical-residue-identity-to-provider-segment-chain-"
                    "and-segment-local-continuous-one-based-position"
                ),
                "call_seed": (
                    "sha256-effective-seed-parent-structure-content-parent-slot-sample-slot"
                ),
                "seed_application": "after-resident-model-resolution",
            },
            model_identity={
                "model": PROTEINMPNN_MODEL,
                "architecture": "ProteinMPNN",
                "source": "dauparas/ProteinMPNN",
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
                "reference_sequence": "complete-backbone-order-explicit-identities-match",
                "sequence_decoding": "complete-parsed-target-layout",
                "incomplete_backbone": (
                    "axis-selected-coordinate-or-provider-NaN-mask;"
                    "fixed-residue-preserved-designable-residue-rejected"
                ),
            },
            scale_contract={
                "sequence": "canonical_20_amino_acids",
            },
        )
    return MethodDefinition(
        method_id=f"proteinmpnn.{operation}.repository_owned",
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
        featurization_identity={
            "layout": "identity-complete-contiguous-chain-layout"
        },
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


def _resolve_score_randomness(
    *,
    inputs: Mapping[str, AdmittedPort],
    node_parameters: Mapping[str, Any],
    binding_parameters: Mapping[str, Any],
) -> dict[str, Any]:
    del inputs, binding_parameters
    return {
        name: node_parameters[name]
        for name in ("effective_seed", "backbone_noise")
    }


def _binding(operation: str) -> ExecutionBindingDefinition:
    is_design = operation == "design"
    is_model = operation in {"design", "score"}
    if is_design:
        randomness_parameters = (
            "effective_seed", "num_sequences", "temperature", "backbone_noise",
        )
        randomness_resolver = _resolve_design_randomness
    elif operation == "score":
        randomness_parameters = ("effective_seed", "backbone_noise")
        randomness_resolver = _resolve_score_randomness
    elif operation == "random_fixed_positions":
        randomness_parameters = ("effective_seed", "fraction")
        randomness_resolver = _resolve_random_fixed_randomness
    else:
        randomness_parameters = ()
        randomness_resolver = None
    method_id = (
        f"proteinmpnn.{operation}.v_48_020_8907e667" + ("_per_sample" if operation == "design" else "")
        if is_model
        else f"proteinmpnn.{operation}.repository_owned"
    )
    produced_observations = (
        (
            ProducedObservation(
                output_port="scores",
                output_partition="default",
                metric=ExactContractReference(
                    "metric",
                    "proteinmpnn.native_sequence_nll",
                ),
                context_profile=PairwiseContextProfile(
                    subject_role="subject",
                    reference_role="reference",
                    pairing_mode="fixed_reference",
                    normalization="provider_masked_mean",
                ),
                reference_source=ObservationPortSource("input", "structure_residue_axes"),
                subject_input="sequence_candidates",
                axis_source=ObservationPortSource("input", "structure_residue_axes"),
                guaranteed_multiplicity="one",
            ),
        )
        if operation == "score"
        else ()
    )
    return ExecutionBindingDefinition(
        binding_id=f"proteinmpnn.{operation}.local",
        node_type=ExactContractReference(
            "node_type",
            f"proteinmpnn.{operation}",
        ),
        method=ExactContractReference(
            "method",
            method_id,
        ),
        binding_parameters={},
        environment_fields=(
            (
                EnvironmentFieldDeclaration("provider_root", "filesystem_path"),
            )
            if is_model
            else ()
        ),
        execution_route="adapter" if is_model else "direct",
        factory=ScientificOperationFactory(
            behavior=BehaviorReference(
                f"proteinmpnn.{operation}/factory",
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
                {
                    "provider_contract": "dauparas/ProteinMPNN",
                    "model": PROTEINMPNN_MODEL,
                    "device_policy": LOCAL_TORCH_DEVICE_POLICY,
                    "device_fallback": "forbidden",
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
                {
                    "observation": "startup",
                    "model_load": "forbidden",
                },
            ),
            prerequisites=(
                {
                    "provider_checkout": {
                        "source": "dauparas/ProteinMPNN",
                    },
                    "runtime": {"name": "torch"},
                }
                if is_model
                else {}
            ),
            check=(
                _model_available
                if is_model
                else AvailabilityResult.available
            ),
        ),
        readiness=(
            ReadinessDeclaration(
                behavior=BehaviorReference(
                    f"proteinmpnn.{operation}/readiness",
                    {
                        "observation": "cache-miss",
                        "cache_order": "before-provider-entry",
                        "model_load": "forbidden",
                        "secret_retention": "none",
                    },
                ),
                prerequisites={
                    "provider_root": {
                        "path_source": "trusted_environment_configuration",
                        "required_relative_files": (
                            PROTEINMPNN_FIXED_ASSET_FILES
                        ),
                    },
                    "device": {
                        "source": "adapter",
                        "policy": LOCAL_TORCH_DEVICE_POLICY,
                        "fallback": "forbidden",
                    },
                },
                check=proteinmpnn_readiness,
            )
            if is_model
            else None
        ),
        deterministic=True,
        cacheable=True,
        effective_randomness_parameters=randomness_parameters,
        effective_randomness_resolver=(
            EffectiveRandomnessResolver(
                behavior=BehaviorReference(
                    f"proteinmpnn.{operation}/effective-randomness",
                    {
                        "normalization": (
                            "resolved-values-and-explicit-layout-v1"
                        )
                    },
                ),
                resolve=randomness_resolver,
            )
            if randomness_resolver is not None
            else None
        ),
        produced_observations=produced_observations,
    )


MODULE_PACKAGE = ModulePackageRegistration(
    package_id="proteinmpnn",
    package_module=__package__,
    port_types=(_port_types.PROTEINMPNN_CONSTRAINTS_PORT_TYPE,),
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


MODULE_PACKAGE = with_adopted_sources(MODULE_PACKAGE, (
    ("adopt_constraints", "proteinmpnn.constraints"),
))
